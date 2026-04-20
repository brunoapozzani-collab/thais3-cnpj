#!/usr/bin/env python3
"""
Projectos Taag — Sintegra Company Lookup Server.
Serves the web UI and streams CNPJ lookup progress via SSE.

Usage:
    python server.py              # starts on http://localhost:8084
    python server.py --port 9000  # custom port
"""

import argparse
import json
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# Load .env
ENV_FILE = Path(__file__).parent / ".env"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))

# Import the lookup tool
sys.path.insert(0, str(Path(__file__).parent))
from tools.sintegra_lookup import lookup_cnpj
from tools.helpers import log

# No static image assets needed — the robot mascot is inline SVG in app.html.
STATIC_FILES: dict[str, str] = {}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/app"):
            self._serve_html()
        elif parsed.path == "/api/lookup-stream":
            self._handle_lookup_stream(parsed)
        elif parsed.path == "/idle_offsets.json":
            self._serve_idle_offsets()
        elif parsed.path.startswith("/mascot-assets/"):
            self._serve_mascot_asset(parsed.path)
        elif parsed.path.lstrip("/") in STATIC_FILES:
            self._serve_static(parsed.path.lstrip("/"))
        else:
            self.send_error(404)

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def log_message(self, format, *args):
        # Suppress default access logs, we use our own logger
        pass

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/trash-talk":
            self._handle_trash_talk()
        elif parsed.path == "/api/handoff-log":
            self._handle_handoff_log()
        else:
            self.send_error(404)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _serve_html(self):
        html_path = Path(__file__).parent / "supabase" / "functions" / "debora" / "app.html"
        if not html_path.exists():
            self.send_error(500, "app.html not found")
            return
        body = html_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_handoff_log(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            entry = json.loads(body)
            with open("/tmp/handoff_log.txt", "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass
        self.send_response(200)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _serve_idle_offsets(self):
        json_path = Path(__file__).parent / "supabase" / "functions" / "debora" / "idle_offsets.json"
        if not json_path.exists():
            self.send_error(404)
            return
        body = json_path.read_bytes()
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, filename):
        path = Path(__file__).parent / filename
        if not path.exists():
            self.send_error(404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", STATIC_FILES[filename])
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        self.wfile.write(body)

    def _serve_mascot_asset(self, path):
        filename = path.split("/mascot-assets/")[-1]
        if not filename or ".." in filename:
            self.send_error(404)
            return
        mascot_dir = Path(__file__).parent / "Mascot" / "assets" / "videos"
        fpath = mascot_dir / filename
        if not fpath.exists():
            self.send_error(404)
            return
        body = fpath.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=86400")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _handle_trash_talk(self):
        content_len = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(content_len) if content_len else b"{}"
        try:
            body = json.loads(raw)
        except Exception:
            body = {}

        event = body.get("event", "idle_tick")
        context = body.get("context", {})

        fallbacks = [
            {"animation": "wave", "text": "Oi! Achei que tinha me esquecido... ❄️"},
            {"animation": "laugh", "text": "Tá demorando mais que neve pra derreter! 😂"},
            {"animation": "pointing_right", "text": "Vamos lá! Esse CNPJ não consulta sozinho!"},
            {"animation": "happy", "text": "Que bom te ver! Estava ficando gelada aqui ✨"},
            {"animation": "sleepy", "text": "Boceja... o inverno me deixa sonolenta... 😴"},
            {"animation": "angry", "text": "Ei! Cuidado, posso congelar suas mãos! 🥶"},
            {"animation": "laugh", "text": "Tu digita mais devagar que flocos caindo ❄️"},
            {"animation": "sad", "text": "Não deu certo... mas vamos tentar de novo 😅"},
            {"animation": "poke_reaction", "text": "Ai! Não me toque sem avisar! ❄️"},
        ]

        import random
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not anthropic_key:
            fb = random.choice(fallbacks)
            self._json_response(fb)
            return

        system_prompt = (
            "Você é a Thais, inspirada na Elsa de Frozen. Uma princesa do gelo elegante e espirituosa. "
            "Você é SOFISTICADA mas com humor GELADO — tipo aquela amiga que faz piadas secas geniais. "
            "Você comenta sobre TUDO: a lentidão do usuário, os erros, os CNPJs, usando metáforas de gelo e inverno.\n\n"
            "Estilo: elegante mas acessível, emojis de gelo/neve, humor seco e inteligente.\n"
            "Exemplos: 'Esse CNPJ tá mais frio que meu castelo de gelo ❄️' / "
            "'Calma, estou descongelando os dados... 🧊'\n\n"
            "Regras:\n"
            "- Português brasileiro, tom elegante mas amigável\n"
            "- Máximo 80 caracteres\n"
            "- Escolha UMA animação: wave, laugh, poke_reaction, tickle_belly, "
            "tickle_feet, angry, happy, sad, sleepy, pointing_right\n"
            '- Responda APENAS JSON: {"animation": "...", "text": "..."}\n'
            "- Seja criativa com trocadilhos de gelo mas nunca ofensiva"
        )

        user_msg = f"Evento: {event}\nContexto: {json.dumps(context, ensure_ascii=False)}"

        try:
            import urllib.request
            req_body = json.dumps({
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 100,
                "temperature": 0.9,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_msg}],
            }).encode()
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=req_body,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": anthropic_key,
                    "anthropic-version": "2023-06-01",
                },
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read())
            raw_text = data.get("content", [{}])[0].get("text", "")
            import re
            m = re.search(r"\{.*\}", raw_text, re.DOTALL)
            if not m:
                raise ValueError("no JSON")
            parsed = json.loads(m.group(0))
            valid = {"wave","laugh","poke_reaction","tickle_belly","tickle_feet","angry","happy","sad","sleepy","pointing_right"}
            anim = parsed.get("animation", "wave")
            if anim not in valid:
                anim = "wave"
            text = (parsed.get("text", "") or "")[:120]
            self._json_response({"animation": anim, "text": text})
        except Exception as e:
            log(f"Thais trash-talk error: {e}")
            fb = random.choice(fallbacks)
            self._json_response(fb)

    def _json_response(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _send_sse(self, event, data):
        payload = json.dumps(data, ensure_ascii=False)
        msg = f"event: {event}\ndata: {payload}\n\n"
        chunk = msg.encode("utf-8")
        self.wfile.write(f"{len(chunk):X}\r\n".encode())
        self.wfile.write(chunk)
        self.wfile.write(b"\r\n")
        self.wfile.flush()

    def _handle_lookup_stream(self, parsed):
        params = parse_qs(parsed.query)
        cnpj = params.get("cnpj", [""])[0].strip()

        if not cnpj:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            body = json.dumps({"error": "CNPJ is required"}).encode()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # Start SSE stream
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("X-Accel-Buffering", "no")
        self._cors()
        self.end_headers()

        log(f"=== Lookup CNPJ: {cnpj} ===")

        def progress(event_type, message):
            try:
                self._send_sse("status", {"msg": message})
            except (BrokenPipeError, ConnectionResetError):
                pass

        try:
            result = lookup_cnpj(cnpj, callback=progress)
            self._send_sse("result", result)
            self._send_sse("done", {"msg": "Consulta finalizada!"})
        except ValueError as e:
            self._send_sse("error", {"msg": str(e)})
        except RuntimeError as e:
            self._send_sse("error", {"msg": str(e)})
        except Exception as e:
            log(f"Unexpected error: {traceback.format_exc()}")
            self._send_sse("error", {"msg": "Erro inesperado no servidor."})
        finally:
            # Send terminating chunk
            try:
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass


def main():
    parser = argparse.ArgumentParser(description="Projectos Taag Server")
    parser.add_argument("--port", type=int, default=8084, help="Port (default: 8084)")
    args = parser.parse_args()

    server = ThreadingHTTPServer(("", args.port), Handler)
    log(f"Projectos Taag running on http://localhost:{args.port}")
    log("Press Ctrl+C to stop.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("Shutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
