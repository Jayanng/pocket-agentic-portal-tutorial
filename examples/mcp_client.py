#!/usr/bin/env python3
"""Minimal MCP client for the Pocket Agentic Portal, stdio transport.

Runs the full safe flow from the tutorial with no wallet and no spending:
handshake -> tool list -> free search -> free describe -> quote-only call.

Requires: Node.js 20+ (the server runs via npx). Python 3.8+, stdlib only.

Usage: python3 examples/mcp_client.py [query]
"""
import json
import os
import subprocess
import sys


def rpc(proc, msg):
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()


def read(proc):
    line = proc.stdout.readline()
    if not line:
        raise RuntimeError("server closed the connection")
    return json.loads(line)


def call_tool(proc, req_id, name, arguments):
    rpc(proc, {"jsonrpc": "2.0", "id": req_id, "method": "tools/call",
               "params": {"name": name, "arguments": arguments}})
    return read(proc)["result"]


def main():
    query = sys.argv[1] if len(sys.argv) > 1 else "web search"

    env = dict(os.environ)
    env["POCKET_QUOTE_ONLY"] = "true"          # never signs, never pays
    env.setdefault("POCKET_MAX_TOTAL_ATOMIC", "1000000")

    proc = subprocess.Popen(
        ["npx", "-y", "@pocket-network/agentic-portal-mcp"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        env=env, text=True,
    )
    try:
        # 1. handshake
        rpc(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                   "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                              "clientInfo": {"name": "pocket-quote-first-example", "version": "1.0"}}})
        info = read(proc)["result"]["serverInfo"]
        print(f"connected to {info['name']} v{info['version']}")
        rpc(proc, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

        # 2. tool inventory
        rpc(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools = [t["name"] for t in read(proc)["result"]["tools"]]
        print("tools:", tools)

        # 3. free: search
        r = call_tool(proc, 3, "search_services", {"query": query, "limit": 3})
        found = json.loads(r["content"][0]["text"])
        print(f"search {query!r}: {found['count']} hit(s)")
        for s in found["services"]:
            print(f"  - {s['serviceId']}  ${s['priceUsd']}/call  [{s['category']}]")

        if not found["services"]:
            print("no matches; try a simpler query")
            return

        # 4. free: describe the first hit
        service_id = found["services"][0]["serviceId"]
        r = call_tool(proc, 4, "describe_service", {"serviceId": service_id})
        described = json.loads(r["content"][0]["text"])
        rail = described["rails"][0]
        print(f"describe {service_id}: ${described['priceUsd']} on {rail['network']} "
              f"({rail['tokenDecimals']} decimals)")

        # 5. paid path, quote only: shows the exact terms a wallet would sign.
        #    The /v1/extract demo call below targets AgentSearch Web Extract when
        #    the catalogue has it, so the request body matches the service.
        extract = next((s for s in found["services"] if "extract" in s["serviceId"]), None)
        if extract is None:
            print("quote demo skipped: web-extract service not in these results")
            return
        r = call_tool(proc, 5, "call_service",
                      {"serviceId": extract["serviceId"], "path": "/v1/extract",
                       "body": {"url": "https://docs.pocket.network/"}})
        quote = json.loads(r["content"][0]["text"])
        if quote.get("quoteOnly"):
            q = quote["quote"]
            dollars = int(q["amount"]) / 10 ** rail["tokenDecimals"]
            pay_to = q["payTo"][:6] + "..." + q["payTo"][-3:]
            print(f"quote: {q['scheme']} {q['amount']} atomic "
                  f"(${dollars:.3f}) on {q['network']} -> {pay_to}")
            print(f"price cross-check: quote ${dollars:.3f} == listed "
                  f"${float(described['priceUsd']):.3f} -> "
                  f"{'OK' if abs(dollars - float(described['priceUsd'])) < 1e-9 else 'MISMATCH'}")
        print("\nnothing was signed (POCKET_QUOTE_ONLY=true)")
    finally:
        if proc.stdin:
            proc.stdin.close()
        proc.wait(timeout=10)


if __name__ == "__main__":
    main()
