import argparse
import json
import os
from pathlib import Path
import secrets
import ipaddress
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .core import Agent, TOOLS
from . import cloud, assistant, code_sync


VERSIONS = {"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"}


def start_peer_sync(agent, port=8766):
    current = getattr(agent, "peer_server", None)
    if current and getattr(current, "peer_thread", None) and current.peer_thread.is_alive():
        return peer_status(agent)
    token = secrets.token_urlsafe(32)

    class PeerHandler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, code, body):
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            if self.path != "/foscp/v1/receive":
                return self.reply(404, {"error": "FOSCP endpoint not found"})
            try:
                address = ipaddress.ip_address(self.client_address[0])
            except ValueError:
                return self.reply(403, {"error": "FOSCP accepts direct private-network peers only"})
            if not (address.is_private or address.is_loopback):
                return self.reply(403, {"error": "FOSCP accepts direct private-network peers only"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 1 <= length <= code_sync.MAX_MESSAGE_BYTES:
                    return self.reply(413, {"error": "FOSCP message size is invalid"})
                payload = self.rfile.read(length)
                proof = self.headers.get("Authorization", "")
                if not code_sync.verify_peer_auth(token, payload, proof):
                    return self.reply(403, {"error": "FOSCP pairing check failed"})
                message = json.loads(payload)
                with agent.lock:
                    result = code_sync.apply_message(agent, message,
                        source="peer:" + str(message.get("origin", {}).get("device_id", "unknown"))[:40])
                return self.reply(200, result)
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                return self.reply(400, {"error": str(exc)[:300]})
            except Exception:
                return self.reply(500, {"error": "FOSCP update could not be applied"})

    class PeerServer(ThreadingHTTPServer):
        daemon_threads = True
        allow_reuse_address = True

    server = PeerServer(("0.0.0.0", port), PeerHandler)
    server.peer_thread = threading.Thread(target=server.serve_forever, name="feather-foscp-peer", daemon=True)
    server.peer_thread.start()
    addresses = code_sync._lan_addresses()
    if not addresses:
        server.shutdown()
        server.server_close()
        server.peer_thread.join(timeout=2)
        raise OSError("No private IPv4 address is available for direct Feather sync")
    server.peer_token = token
    server.peer_addresses = ["http://" + address + ":" + str(server.server_port) + "/foscp/v1/receive"
                             for address in addresses]
    agent.peer_server = server
    return peer_status(agent)


def stop_peer_sync(agent):
    server = getattr(agent, "peer_server", None)
    if not server:
        return {"enabled": False}
    server.shutdown()
    server.server_close()
    if server.peer_thread.is_alive():
        server.peer_thread.join(timeout=2)
    agent.peer_server = None
    return {"enabled": False}


def peer_status(agent):
    server = getattr(agent, "peer_server", None)
    if not server or not server.peer_thread.is_alive():
        return {"enabled": False}
    return {"enabled": True, "addresses": server.peer_addresses,
            "pairing_key": server.peer_token, "device_id": code_sync._device_id(agent.data)}


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
    html = (Path(__file__).parent / "desktop.html").read_text(encoding="utf-8").replace("__TOKEN__", token)

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
                            "ai": assistant.status(agent),
                            "mcp_connected": agent.mcp_connected,
                            "revisions": agent.call("revision_list", {}),
                            "code_changes": code_sync.history(agent),
                            "peer_sync": peer_status(agent)}
                return self.reply(200, json.dumps(body))
            if self.path.startswith("/api/code/change/"):
                change_id = self.path.removeprefix("/api/code/change/")
                try:
                    message = code_sync.get_message(agent, change_id)
                    return self.reply(200, json.dumps({"patch": code_sync.preview_message(message)}))
                except ValueError as exc:
                    return self.reply(404, json.dumps({"error": str(exc)}))
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
                    if not assistant.configured(agent):
                        return self.reply(503, json.dumps({"error": "The selected AI provider is not connected."}))
                    result = agent.submit(body.get("text"))
                elif self.path == "/api/snapshot":
                    result = agent.call("revision_save", {"root": "source", "label": "Desktop checkpoint"})
                elif self.path == "/api/peer/start":
                    result = start_peer_sync(agent)
                elif self.path == "/api/peer/stop":
                    result = stop_peer_sync(agent)
                elif self.path == "/api/peer/send":
                    message = code_sync.get_message(agent, body.get("change_id"))
                    result = code_sync.send_message(body.get("url"), body.get("pairing_key"), message)
                else:
                    return self.reply(404, '{"error":"Not found"}')
                return self.reply(200, json.dumps(result))
            except (ValueError, AttributeError, OSError) as e:
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
    if assistant.configured(agent):
        threading.Thread(target=assistant.worker, args=(agent, stop), daemon=True).start()
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
        stop_peer_sync(agent)
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
