"""GuideGlass Windows bridge and local spatial reconstruction server."""
import argparse
import ipaddress
import json
import re
import socket
import ssl
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import URLError, HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import build_opener, ProxyHandler, HTTPRedirectHandler

PORT = 8766
ROOT = Path(__file__).resolve().parent
DEVICE = {"ip": None, "camera_port": 80, "distance_port": 82}
PRIVATE_NETWORKS = [ipaddress.ip_network(s) for s in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]


def local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 80))
            return s.getsockname()[0]
    except OSError:
        return "YOUR_WINDOWS_IP"


def valid_private_device(ip):
    try:
        addr = ipaddress.ip_address(ip)
        return isinstance(addr, ipaddress.IPv4Address) and any(addr in network for network in PRIVATE_NETWORKS)
    except ValueError:
        return False


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("The LAN device must not redirect to another service")


class GuideGlassServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, root=ROOT, allowed_hosts=()):
        self.root = Path(root)
        self.device = dict(DEVICE)
        self.allowed_hosts = set(allowed_hosts)
        self.spatial_error = None
        try:
            from guideglass.engine import SpatialEngine
            self.spatial = SpatialEngine(self.root, lambda: self.device_fetch("/capture", 80, 2000000)[0])
        except ImportError as error:
            self.spatial = None
            self.spatial_error = f"Run setup_windows.bat for spatial dependencies ({error.name})"
        super().__init__(address, Handler)

    def device_fetch(self, path, port, maximum):
        if not self.device["ip"]:
            raise ValueError("ESP32 address not configured")
        url = f"http://{self.device['ip']}:{port}{path}"
        with build_opener(ProxyHandler({}), NoRedirect()).open(url, timeout=2.5) as response:
            raw = response.read(maximum + 1)
            if len(raw) > maximum: raise ValueError("Device response too large")
            return raw, response.headers.get("Content-Type", "")

    def server_close(self):
        if self.spatial: self.spatial.stop()
        super().server_close()


class Handler(BaseHTTPRequestHandler):
    server_version = "GuideGlass/0.2"

    def setup(self):
        super().setup()
        self.connection.settimeout(45)

    def _reply(self, code, body=b"", content_type="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.end_headers()
        try: self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError): pass

    def json_reply(self, code, obj):
        data = json.dumps(obj, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self._reply(code, data)

    def _trusted_host(self):
        try: host = urlsplit("//" + self.headers.get("Host", "")).hostname
        except ValueError: return False
        if host in {"localhost", "127.0.0.1", "::1"} | self.server.allowed_hosts: return True
        return bool(host and valid_private_device(host))

    def _read_body(self, maximum):
        if self.headers.get("Transfer-Encoding"): raise ValueError("Use a bounded Content-Length request")
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= maximum: raise ValueError("Invalid request size")
        body = self.rfile.read(length)
        if len(body) != length: raise ValueError("Incomplete request")
        return body

    def _json_body(self):
        if self.headers.get_content_type() != "application/json": raise ValueError("JSON content type required")
        value = json.loads(self._read_body(20000))
        if not isinstance(value, dict): raise ValueError("Expected a JSON object")
        return value

    def do_POST(self):
        if not self._trusted_host(): return self.json_reply(403, {"error": "Host is not configured"})
        origin = self.headers.get("Origin")
        if origin and urlsplit(origin).netloc != self.headers.get("Host"):
            return self.json_reply(403, {"error": "Cross-origin control is not permitted"})
        parsed = urlsplit(self.path); path = parsed.path
        try:
            if path == "/api/device":
                payload = self._json_body()
                ip = str(payload.get("ip", "")).strip()
                if not valid_private_device(ip): raise ValueError("Enter a private LAN IPv4 address for the ESP32")
                self.server.device["ip"] = ip
                return self.json_reply(200, {"ok": True, "ip": ip})
            engine = self.server.spatial
            if engine is None: return self.json_reply(503, {"error": self.server.spatial_error})
            if path == "/api/spatial/start": return self.json_reply(200, engine.start(self._json_body()))
            if path == "/api/spatial/stop":
                self._json_body()
                return self.json_reply(200, engine.stop())
            if path == "/api/spatial/save": return self.json_reply(200, engine.save_map(self._json_body().get("name", "")))
            if path == "/api/spatial/load": return self.json_reply(200, engine.load_map(self._json_body().get("id")))
            if path == "/api/spatial/frame":
                query = parse_qs(parsed.query)
                if self.headers.get_content_type() not in {"image/jpeg", "image/png"}: raise ValueError("JPEG/PNG frame required")
                engine.submit_frame(self._read_body(5000000), query.get("session", [""])[0], float(query.get("timestamp", ["nan"])[0]))
                return self.json_reply(202, {"accepted": True})
            if path == "/api/spatial/upload": return self._upload_video()
            return self.json_reply(404, {"error": "Not found"})
        except (ValueError, TypeError, KeyError, OSError) as e:
            self.json_reply(400, {"error": str(e)})

    def do_GET(self):
        if not self._trusted_host(): return self.json_reply(403, {"error": "Host is not configured"})
        parsed = urlsplit(self.path); path = parsed.path
        if path == "/":
            return self._serve_html()
        if path == "/api/status":
            return self.json_reply(200, {"bridge": "ready", "ip": self.server.device["ip"],
                                       "ai": bool(self.server.spatial), "spatial_error": self.server.spatial_error})
        if path == "/api/frame":
            return self._proxy("/capture", self.server.device["camera_port"], "image/jpeg")
        if path == "/api/distance":
            return self._proxy("/distance", self.server.device["distance_port"], "application/json")
        assets = {"/static/spatial.js": ("static/spatial.js", "text/javascript; charset=utf-8"),
                  "/static/spatial.css": ("static/spatial.css", "text/css; charset=utf-8"),
                  "/vendor/three.module.js": ("vendor/three.module.js", "text/javascript; charset=utf-8"),
                  "/vendor/OrbitControls.js": ("vendor/OrbitControls.js", "text/javascript; charset=utf-8")}
        if path in assets:
            file, mime = assets[path]; asset = self.server.root / file
            if not asset.is_file(): return self.json_reply(503, {"error": "Run tools/prepare_assets.py --web"})
            return self._reply(200, asset.read_bytes(), mime)
        if path.startswith("/api/spatial/"):
            engine = self.server.spatial
            if engine is None: return self.json_reply(503, {"error": self.server.spatial_error})
            try:
                if path == "/api/spatial/state": return self.json_reply(200, engine.state())
                if path == "/api/spatial/cloud":
                    since = parse_qs(parsed.query).get("since", [None])[0]
                    body = engine.cloud(int(since) if since is not None else None)
                    return self._reply(304 if body is None else 200, body or b"", "application/octet-stream")
                if path in {"/api/spatial/frame", "/api/spatial/depth"}:
                    with engine.lock: body = engine.frame_jpeg if path.endswith("frame") else engine.depth_jpeg
                    if body is None: return self.json_reply(404, {"error": "No processed frame yet"})
                    return self._reply(200, body, "image/jpeg")
                if path == "/api/spatial/maps": return self.json_reply(200, {"maps": engine.maps.list()})
                match = re.fullmatch(r"/api/spatial/maps/([0-9a-f]{32})\.ply", path)
                if match: return self._reply(200, engine.maps.ply(match[1]), "application/octet-stream")
            except (ValueError, TypeError, OSError) as e: return self.json_reply(400, {"error": str(e)})
        self.json_reply(404, {"error": "Not found"})

    def _serve_html(self):
        data = (self.server.root / "index.html").read_bytes()
        self._reply(200, data, "text/html; charset=utf-8")

    def _upload_video(self):
        if self.headers.get_content_type() not in {"video/mp4", "video/quicktime", "application/octet-stream"}:
            raise ValueError("Upload an MP4 or MOV video")
        if self.headers.get("Transfer-Encoding"): raise ValueError("Content-Length required")
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 < size <= 120000000: raise ValueError("Video limit: 120 MB")
        folder = self.server.root / ".data/uploads"; folder.mkdir(parents=True, exist_ok=True)
        video_id = uuid.uuid4().hex; temporary = folder / (video_id + ".part")
        try:
            with temporary.open("wb") as output:
                remaining = size
                while remaining:
                    chunk = self.rfile.read(min(remaining, 1024 * 1024))
                    if not chunk: raise ValueError("Incomplete video upload")
                    output.write(chunk); remaining -= len(chunk)
            import cv2
            capture = cv2.VideoCapture(str(temporary))
            try:
                width, height = capture.get(cv2.CAP_PROP_FRAME_WIDTH), capture.get(cv2.CAP_PROP_FRAME_HEIGHT)
                if width * height > 12000000: raise ValueError("Video resolution exceeds 12 megapixels")
                ok, frame = capture.read()
            finally: capture.release()
            if not ok or frame is None or frame.shape[0] * frame.shape[1] > 12000000:
                raise ValueError("Video could not be decoded or is larger than supported resolution")
            temporary.replace(folder / (video_id + ".mp4"))
            return self.json_reply(201, {"video_id": video_id, "bytes": size})
        finally:
            if temporary.exists(): temporary.unlink()

    def _proxy(self, path, port, content_type):
        if not self.server.device["ip"]:
            return self.json_reply(503, {"error": "ESP32 address not configured"})
        try:
            raw, typ = self.server.device_fetch(path, port, 2000000 if content_type == "image/jpeg" else 20000)
            if content_type == "image/jpeg" and not typ.lower().startswith("image/"):
                raise ValueError("Camera did not return an image")
            if content_type == "application/json": return self.json_reply(200, json.loads(raw))
            self._reply(200, raw, "image/jpeg")
        except (URLError, HTTPError, TimeoutError, ValueError, OSError) as e:
            self.json_reply(502, {"error": "Device unavailable", "detail": str(e)[:250]})

    def log_message(self, fmt, *args):
        if not self.path.startswith("/api/"):
            super().log_message(fmt, *args)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--allow-host", action="append", default=[])
    parser.add_argument("--tls-cert")
    parser.add_argument("--tls-key")
    args = parser.parse_args()
    if bool(args.tls_cert) != bool(args.tls_key): parser.error("Provide both TLS certificate and key")
    server = GuideGlassServer((args.host, args.port), allowed_hosts=args.allow_host)
    scheme = "http"
    if args.tls_cert:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(args.tls_cert, args.tls_key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        scheme = "https"
    print("\nGuideGlass AI v0.2 - LOCAL SPATIAL RECONSTRUCTION", flush=True)
    print("Open on iPhone Safari (same Wi-Fi):")
    print(f"  {scheme}://{local_ip()}:{args.port}", flush=True)
    print("\nIf that address fails, use 'ipconfig' to find your Windows IPv4.")
    print("Allow Python through Windows Firewall on PRIVATE networks only.")
    print("Windows and iPhone must be on the SAME Wi-Fi. Ctrl+C to stop.\n")
    print("Safari camera capture requires trusted HTTPS; viewing Windows/test-video results works on LAN HTTP.", flush=True)
    if server.spatial_error: print(server.spatial_error, flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
