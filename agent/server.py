import argparse
import json
import os
from pathlib import Path
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .core import Agent, TOOLS
from . import cloud


VERSIONS = {"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"}


def rpc(agent, request):
    if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid request"}}
    if "id" not in request:
        return None
    base = {"jsonrpc": "2.0", "id": request["id"]}
    method, params = request.get("method"), request.get("params", {})
    if not isinstance(params, dict):
        return dict(base, error={"code": -32602, "message": "Invalid params"})
    if method == "initialize":
        agent.mcp_connected = True
        version = params.get("protocolVersion")
        return dict(base, result={"protocolVersion": version if version in VERSIONS else "2025-11-25",
            "capabilities": {"tools": {}}, "serverInfo": {"name": "feather-local-agent", "version": "0.2.0"},
            "instructions": "Use task_next to claim dashboard requests, tools to carry out the task, and task_reply to show the result."})
    if method == "ping":
        return dict(base, result={})
    if method == "tools/list":
        return dict(base, result={"tools": TOOLS})
    if method == "tools/call":
        try:
            result = agent.call(params.get("name"), params.get("arguments", {}))
            content = {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}
        except Exception as e:
            content = {"isError": True, "content": [{"type": "text", "text": str(e)}]}
        return dict(base, result=content)
    # Modern clients may probe server/discover; reply so they can negotiate legacy MCP.
    return dict(base, error={"code": -32601, "message": "Method not found; this starter supports MCP initialize lifecycle"})


def stdio(agent):
    for line in sys.stdin:
        try:
            request = json.loads(line)
            result = rpc(agent, request)
        except json.JSONDecodeError:
            result = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        if result is not None:
            sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
            sys.stdout.flush()


def make_http(agent, port=8765):
    token = secrets.token_urlsafe(32)
    html = (Path(__file__).parent / "desktop.html").read_text().replace("__TOKEN__", token)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def valid_host(self):
            return self.headers.get("Host") in {"127.0.0.1:" + str(self.server.server_port),
                                                "localhost:" + str(self.server.server_port)}

        def authorised(self):
            origin = self.headers.get("Origin")
            allowed = {"http://127.0.0.1:" + str(self.server.server_port),
                       "http://localhost:" + str(self.server.server_port)}
            return self.valid_host() and (not origin or origin in allowed) and secrets.compare_digest(
                self.headers.get("X-Feather-Token", ""), token)

        def reply(self, code, body, kind="application/json"):
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", kind + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/" and self.valid_host():
                return self.reply(200, html, "text/html")
            if not self.authorised():
                return self.reply(403, '{"error":"Local session required"}')
            if self.path == "/api/state":
                with agent.lock:
                    body = {"system": agent.call("system_info", {}), "tasks": list(agent.tasks),
                            "cloud_configured": cloud.configured(),
                            "mcp_connected": agent.mcp_connected,
                            "revisions": agent.call("revision_list", {})}
                return self.reply(200, json.dumps(body))
            return self.reply(404, '{"error":"Not found"}')

        def do_POST(self):
            if not self.authorised():
                return self.reply(403, '{"error":"Local session required"}')
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 40000:
                    raise ValueError("Invalid request size")
                body = json.loads(self.rfile.read(length))
                if self.path == "/api/task":
                    result = agent.submit(body.get("text"))
                elif self.path == "/api/snapshot":
                    result = agent.call("revision_save", {"root": "source", "label": "Desktop checkpoint"})
                else:
                    return self.reply(404, '{"error":"Not found"}')
                return self.reply(200, json.dumps(result))
            except (ValueError, AttributeError) as e:
                return self.reply(400, json.dumps({"error": str(e)}))

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main(default_data_dir="feather-data", default_source_dir=None):
    parser = argparse.ArgumentParser(description="Feather local AI/MCP agent")
    parser.add_argument("--data-dir", default=default_data_dir)
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--mcp", action="store_true", help="Use newline JSON-RPC on stdin/stdout")
    parser.add_argument("--enable-commands", action="store_true", help="Allow commands with current-user privileges")
    args = parser.parse_args()
    source_dir = default_source_dir or Path(__file__).resolve().parents[1]
    agent = Agent(args.data_dir, source_dir, args.enable_commands)
    server = make_http(agent, args.port)
    stop = threading.Event()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    if cloud.configured():
        threading.Thread(target=cloud.worker, args=(agent, stop), daemon=True).start()
    if sys.stderr is not None:
        print("Feather desktop: http://127.0.0.1:" + str(server.server_port), file=sys.stderr, flush=True)
    try:
        if args.mcp:
            stdio(agent)
        else:
            stop.wait()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
