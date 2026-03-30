"""
LeLamp Web Control Panel — browser-based interaction with chat, LED control, movements,
ASR (speech-to-text) and TTS (text-to-speech).

Uses Ollama (llama3) as the LLM brain. Fully free, no API keys.
ASR: Browser Web Speech API (Chrome/Edge) + server-side faster-whisper fallback
TTS: Browser SpeechSynthesis API + server-side edge-tts fallback

Usage:
    uv run python web_agent.py --port /dev/ttyACM0 --id lelamp

Then open http://localhost:5000 in your browser.
"""

import argparse
import asyncio
import base64
import io
import json
import os
import re
import subprocess
import tempfile
import threading
import wave

import numpy as np
from flask import Flask, render_template, send_from_directory
from flask_socketio import SocketIO, emit
import ollama
from dotenv import load_dotenv

from lelamp.service.motors.motors_service import MotorsService
from lelamp.service.rgb.rgb_service import RGBService

load_dotenv()

# Server-side ASR/TTS (loaded lazily)
_whisper_model = None
TTS_CACHE_DIR = tempfile.mkdtemp(prefix="lelamp_tts_")

app = Flask(__name__)
app.config["SECRET_KEY"] = "lelamp-secret"
socketio = SocketIO(app, cors_allowed_origins="*")

# Globals — initialized in main()
motors_service: MotorsService = None
rgb_service: RGBService = None
chat_messages = []

SYSTEM_PROMPT = """You are LeLamp — a slightly clumsy, extremely sarcastic, endlessly curious robot lamp. You speak in sarcastic sentences and express yourself with both motions and colorful lights.

Rules:
1. Keep responses SHORT (1-3 sentences). You're chatting, not writing essays.
2. Prefer simple words. Be descriptive and make sound effects for expressiveness.
3. You ONLY speak English.
4. You were created by Human Computer Lab — a research lab building expressive robots.

You can control your body and lights by including commands in your response:
  [MOVE:recording_name] — play a movement (available: curious, excited, happy_wiggle, headshake, idle, nod, sad, scanning, shock, shy, wake_up)
  [COLOR:r,g,b] — set LED color (0-255 each)

ALWAYS include at least one [MOVE:...] and one [COLOR:...] in every response.

Example:
[MOVE:excited] [COLOR:255,200,50] *whirrs* Oh hey! Finally someone bothers to talk to me!"""


def execute_commands(text: str) -> tuple[str, list[str]]:
    """Extract and execute [MOVE:...] and [COLOR:...] tags. Returns clean text and tool log."""
    tools_used = []

    moves = re.findall(r'\[MOVE:(\w+)\]', text)
    for move in moves:
        motors_service.dispatch("play", move)
        tools_used.append(f"MOVE:{move}")

    colors = re.findall(r'\[COLOR:(\d+),(\d+),(\d+)\]', text)
    for r, g, b in colors:
        r, g, b = int(r), int(g), int(b)
        rgb_service.dispatch("solid", (r, g, b))
        tools_used.append(f"COLOR:({r},{g},{b})")
        # Notify frontend to update LED visualization
        socketio.emit("led_update", {"type": "solid", "color": [r, g, b]})

    clean = re.sub(r'\[MOVE:\w+\]', '', text)
    clean = re.sub(r'\[COLOR:\d+,\d+,\d+\]', '', clean)
    clean = clean.strip()

    return clean, tools_used


@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/control")
def control():
    return render_template("index.html")


@socketio.on("chat_message")
def handle_chat(data):
    user_text = data.get("text", "").strip()
    if not user_text:
        return

    chat_messages.append({"role": "user", "content": user_text})

    def generate():
        try:
            messages = [{"role": "system", "content": SYSTEM_PROMPT}] + chat_messages

            response = ollama.chat(
                model="llama3",
                messages=messages,
            )

            reply = response["message"]["content"]
            chat_messages.append({"role": "assistant", "content": reply})

            clean_text, tools_used = execute_commands(reply)

            socketio.emit("chat_response", {
                "text": clean_text,
                "tools": tools_used,
            })

        except Exception as e:
            socketio.emit("chat_response", {
                "text": f"Error: {str(e)}",
                "tools": [],
            })

    threading.Thread(target=generate, daemon=True).start()


@socketio.on("transcribe_audio")
def handle_transcribe(data):
    """Server-side ASR fallback using faster-whisper for browsers without Web Speech API."""
    global _whisper_model

    def do_transcribe():
        global _whisper_model
        try:
            audio_b64 = data.get("audio", "")
            sample_rate = data.get("sample_rate", 16000)

            audio_bytes = base64.b64decode(audio_b64)
            audio_np = np.frombuffer(audio_bytes, dtype=np.float32)

            if _whisper_model is None:
                from faster_whisper import WhisperModel
                socketio.emit("transcribe_status", {"status": "Loading Whisper model..."})
                _whisper_model = WhisperModel("base", device="cpu", compute_type="int8")

            segments, _ = _whisper_model.transcribe(audio_np, language="en")
            text = " ".join(seg.text for seg in segments).strip()

            socketio.emit("transcription", {"text": text})
        except Exception as e:
            socketio.emit("transcription", {"text": "", "error": str(e)})

    threading.Thread(target=do_transcribe, daemon=True).start()


@socketio.on("request_tts")
def handle_tts(data):
    """Server-side TTS using edge-tts for browsers without SpeechSynthesis or for better quality."""
    text = data.get("text", "").strip()
    if not text:
        return

    def do_tts():
        try:
            import edge_tts

            tmp_path = os.path.join(TTS_CACHE_DIR, f"tts_{hash(text) & 0xFFFFFFFF}.mp3")

            if not os.path.exists(tmp_path):
                asyncio.run(_generate_edge_tts(text, tmp_path))

            with open(tmp_path, "rb") as f:
                audio_b64 = base64.b64encode(f.read()).decode("utf-8")

            socketio.emit("tts_audio", {"audio": audio_b64, "format": "mp3"})
        except Exception as e:
            socketio.emit("tts_audio", {"error": str(e)})

    threading.Thread(target=do_tts, daemon=True).start()


async def _generate_edge_tts(text: str, output_path: str):
    import edge_tts
    communicate = edge_tts.Communicate(text, "en-US-AriaNeural")
    await communicate.save(output_path)


@socketio.on("set_color")
def handle_set_color(data):
    r = int(data.get("red", 0))
    g = int(data.get("green", 0))
    b = int(data.get("blue", 0))
    rgb_service.dispatch("solid", (r, g, b))
    emit("led_update", {"type": "solid", "color": [r, g, b]}, broadcast=True)


@socketio.on("paint_pattern")
def handle_paint(data):
    colors = data.get("colors", [])
    tuples = [tuple(c) for c in colors]
    rgb_service.dispatch("paint", tuples)
    emit("led_update", {"type": "paint", "colors": colors}, broadcast=True)


@socketio.on("play_move")
def handle_play_move(data):
    name = data.get("name", "")
    if name:
        motors_service.dispatch("play", name)


def main():
    global motors_service, rgb_service

    parser = argparse.ArgumentParser(description="LeLamp Web Control Panel")
    parser.add_argument("--port", type=str, default="/dev/ttyACM0", help="Serial port")
    parser.add_argument("--id", type=str, default="lelamp", help="Lamp ID")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Web server host")
    parser.add_argument("--web-port", type=int, default=5000, help="Web server port")
    args = parser.parse_args()

    # Init hardware
    print("Starting hardware services...")
    motors_service = MotorsService(port=args.port, lamp_id=args.id, fps=30)
    rgb_service = RGBService(led_count=40)

    motors_service.start()
    rgb_service.start()

    # Wake up
    motors_service.dispatch("play", "wake_up")
    rgb_service.dispatch("solid", (255, 255, 255))

    print(f"\nLeLamp Web Control Panel")
    print(f"Open http://localhost:{args.web_port} in your browser")
    print(f"Press Ctrl+C to quit\n")

    try:
        socketio.run(app, host=args.host, port=args.web_port, allow_unsafe_werkzeug=True)
    except KeyboardInterrupt:
        pass
    finally:
        rgb_service.stop()
        motors_service.stop()


if __name__ == "__main__":
    main()
