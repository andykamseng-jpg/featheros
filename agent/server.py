import argparse
import json
import os
from pathlib import Path
import secrets
import ipaddress
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .core import Agent, TOOLS
from . import cloud, assistant, code_sync, f2f_cloud


VERSIONS = {"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"}
PEER_DISCOVERY_GROUP = "239.255.60.60"
PEER_DISCOVERY_PORT = 8767
PEER_DISCOVERY_INTERVAL = 3
PEER_SYNC_INTERVAL = 10


def _private_source(address):
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    return parsed.is_private or parsed.is_loopback


def _peer_get(address, path, token=None):
    from urllib.parse import urlparse

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, response, code, message, headers, new_url):
            raise ValueError("FOSCP peers cannot redirect network requests")

    parsed = urlparse(address)
    payload = b""
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = code_sync.peer_auth_header(token, payload)
    request = urllib.request.Request("http://" + parsed.netloc + path, headers=headers, method="GET")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=8) as response:
            data = response.read(code_sync.MAX_MESSAGE_BYTES + 1)
            if len(data) > code_sync.MAX_MESSAGE_BYTES:
                raise ValueError("Peer response exceeds the FOSCP limit")
            return json.loads(data)
    except urllib.error.HTTPError as exc:
        try:
            message = json.loads(exc.read(4096).decode("utf-8", "replace")).get("error")
        except (ValueError, AttributeError):
            message = None
        raise ValueError(message or "Peer rejected the FOSCP request") from exc


def _sync_peer(agent, address, port, expected_id):
    base = "http://" + address + ":" + str(port)
    info = _peer_get(base, "/foscp/v1/info")
    peer_id = info.get("device_id") if isinstance(info, dict) else None
    peer_key = info.get("pairing_key") if isinstance(info, dict) else None
    if peer_id != expected_id or not isinstance(peer_key, str) or len(peer_key) < 32:
        raise ValueError("Discovered Feather identity did not match its network announcement")
    updates = _peer_get(base, "/foscp/v1/updates", peer_key)
    identifiers = updates.get("changes", []) if isinstance(updates, dict) else []
    if not isinstance(identifiers, list) or len(identifiers) > 50:
        raise ValueError("Peer sent an invalid FOSCP update list")
    applied = rejected = 0
    last_error = None
    with agent.lock:
        for change_id in identifiers:
            if not isinstance(change_id, str) or len(change_id) != 32:
                continue
            if code_sync._record_path(agent, change_id).exists():
                continue
            message = _peer_get(base, "/foscp/v1/change/" + change_id, peer_key)
            try:
                code_sync.apply_message(agent, message, source="peer:" + peer_id)
                applied += 1
            except (ValueError, OSError) as exc:
                # Keep independent updates moving if a stale base or a different
                # hardware fingerprint makes one patch inapplicable here.
                rejected += 1
                last_error = str(exc)[:160]
                continue
    return {"applied": applied, "rejected": rejected, "last_error": last_error}


def _peer_discovery_loop(agent, server):
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except (AttributeError, OSError):
            pass
        sock.bind(("", PEER_DISCOVERY_PORT))
        membership = socket.inet_aton(PEER_DISCOVERY_GROUP) + socket.inet_aton("0.0.0.0")
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        sock.settimeout(0.5)
        server.discovery_socket = sock
        last_advertisement = 0.0
        last_sync = {}
        while not server.peer_stop.is_set():
            now = time.monotonic()
            if now - last_advertisement >= PEER_DISCOVERY_INTERVAL:
                beacon = json.dumps({"protocol": "FOSCP-DISCOVERY/1",
                    "device_id": code_sync._device_id(agent.data),
                    "port": server.server_port}, separators=(",", ":")).encode("utf-8")
                try:
                    sock.sendto(beacon, (PEER_DISCOVERY_GROUP, PEER_DISCOVERY_PORT))
                except OSError:
                    pass
                last_advertisement = now
            try:
                raw, (address, _source_port) = sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                if server.peer_stop.is_set():
                    break
                continue
            if not _private_source(address):
                continue
            try:
                beacon = json.loads(raw.decode("utf-8"))
                peer_id = beacon.get("device_id")
                peer_port = beacon.get("port")
                if (beacon.get("protocol") != "FOSCP-DISCOVERY/1" or
                        not isinstance(peer_id, str) or len(peer_id) != 32 or
                        any(ch not in "0123456789abcdef" for ch in peer_id) or
                        not isinstance(peer_port, int) or not 1 <= peer_port <= 65535):
                    continue
            except (UnicodeError, ValueError, AttributeError):
                continue
            if peer_id == code_sync._device_id(agent.data):
                continue
            with server.peer_lock:
                peer_state = server.peer_devices.setdefault(peer_id, {"device_id": peer_id,
                    "address": address, "port": peer_port, "status": "discovered"})
                peer_state.update({"address": address, "port": peer_port, "last_seen": time.time()})
            if now - last_sync.get(peer_id, 0) < PEER_SYNC_INTERVAL:
                continue
            last_sync[peer_id] = now
            try:
                sync_result = _sync_peer(agent, address, peer_port, peer_id)
                with server.peer_lock:
                    server.peer_devices[peer_id].update({"status": "connected", "last_sync": time.time(),
                        **sync_result, "error": sync_result.get("last_error")})
            except (OSError, ValueError, urllib.error.URLError) as exc:
                with server.peer_lock:
                    server.peer_devices[peer_id].update({"status": "unreachable", "error": str(exc)[:160]})
    except OSError as exc:
        server.discovery_error = str(exc)[:160]
        if not server.peer_stop.is_set():
            retry = threading.Thread(target=_retry_peer_discovery, args=(agent, server),
                name="feather-foscp-discovery-retry", daemon=True)
            server.discovery_retry = retry
            retry.start()
    finally:
        server.discovery_socket = None
        if sock:
            try:
                sock.close()
            except OSError:
                pass


def _retry_peer_discovery(agent, server):
    if server.peer_stop.wait(5) or getattr(agent, "peer_server", None) is not server:
        return
    thread = threading.Thread(target=_peer_discovery_loop, args=(agent, server),
        name="feather-foscp-discovery", daemon=True)
    server.discovery_thread = thread
    thread.start()


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

        def private_request(self):
            return _private_source(self.client_address[0])

        def authenticated_get(self):
            return code_sync.verify_peer_auth(token, b"", self.headers.get("Authorization", ""))

        def do_GET(self):
            if not self.private_request():
                return self.reply(403, {"error": "FOSCP accepts direct private-network peers only"})
            if self.path == "/foscp/v1/info":
                return self.reply(200, {"protocol": "FOSCP/1",
                    "device_id": code_sync._device_id(agent.data), "pairing_key": token})
            if not self.authenticated_get():
                return self.reply(403, {"error": "FOSCP peer authentication failed"})
            if self.path == "/foscp/v1/updates":
                with agent.lock:
                    changes = [row["id"] for row in reversed(code_sync.history(agent, limit=50)) if row.get("id")]
                return self.reply(200, {"changes": changes})
            prefix = "/foscp/v1/change/"
            if self.path.startswith(prefix):
                change_id = self.path[len(prefix):]
                try:
                    with agent.lock:
                        message = code_sync.get_message(agent, change_id)
                    return self.reply(200, message)
                except ValueError as exc:
                    return self.reply(404, {"error": str(exc)})
            return self.reply(404, {"error": "FOSCP endpoint not found"})

        def do_POST(self):
            if self.path != "/foscp/v1/receive":
                return self.reply(404, {"error": "FOSCP endpoint not found"})
            if not self.private_request():
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
    server.peer_stop = threading.Event()
    server.peer_devices = {}
    server.peer_lock = threading.Lock()
    server.discovery_error = None
    server.peer_thread = threading.Thread(target=server.serve_forever, name="feather-foscp-peer-http", daemon=True)
    server.peer_thread.start()
    addresses = code_sync._lan_addresses()
    server.peer_token = token
    server.peer_addresses = ["http://" + address + ":" + str(server.server_port) + "/foscp/v1/receive"
                             for address in addresses]
    agent.peer_server = server
    server.discovery_thread = threading.Thread(target=_peer_discovery_loop, args=(agent, server),
        name="feather-foscp-discovery", daemon=True)
    server.discovery_thread.start()
    return peer_status(agent)


def stop_peer_sync(agent):
    server = getattr(agent, "peer_server", None)
    if not server:
        return {"enabled": False}
    server.peer_stop.set()
    discovery_socket = getattr(server, "discovery_socket", None)
    if discovery_socket:
        try:
            discovery_socket.close()
        except OSError:
            pass
    server.shutdown()
    server.server_close()
    if server.peer_thread.is_alive():
        server.peer_thread.join(timeout=2)
    discovery_thread = getattr(server, "discovery_thread", None)
    if discovery_thread and discovery_thread.is_alive():
        discovery_thread.join(timeout=2)
    agent.peer_server = None
    return {"enabled": False}


def peer_status(agent):
    server = getattr(agent, "peer_server", None)
    if not server or not server.peer_thread.is_alive():
        return {"enabled": False, "automatic": True, "scope": "private-network"}
    with server.peer_lock:
        peers = [dict(peer) for peer in server.peer_devices.values()]
    now = time.time()
    for peer in peers:
        if now - peer.get("last_seen", 0) > 30:
            peer["status"] = "offline"
    return {"enabled": True, "automatic": True, "scope": "private-network",
            "addresses": ["http://" + address + ":" + str(server.server_port) + "/foscp/v1/receive"
                          for address in code_sync._lan_addresses()],
            "device_id": code_sync._device_id(agent.data),
            "discovery_error": server.discovery_error,
            "peers": sorted(peers, key=lambda peer: peer.get("device_id", ""))}


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
                            "f2f_relay": getattr(agent, "f2f_relay_status", {"configured": f2f_cloud.configured(), "status": "starting"}),
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
    try:
        start_peer_sync(agent)
    except OSError:
        pass
    server = make_http(agent, args.port)
    stop = threading.Event()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    threading.Thread(target=f2f_cloud.worker, args=(agent, stop),
                     name="feather-f2f-cloud", daemon=True).start()
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
