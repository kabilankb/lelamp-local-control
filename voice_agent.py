"""
LeLamp Offline Voice Agent — fully local, no API keys needed.

ASR:  faster-whisper (local Whisper model)
LLM:  Ollama (llama3)
TTS:  edge-tts (free Microsoft TTS)

Usage:
    uv run python voice_agent.py --port /dev/ttyACM0 --id lelamp

Prerequisites:
    - Ollama running with llama3: ollama pull llama3
    - Microphone connected
    - Speakers/headphones connected
"""

import argparse
import asyncio
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import wave

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel
import edge_tts
import ollama
from dotenv import load_dotenv

from lelamp.service.motors.motors_service import MotorsService
from lelamp.service.rgb.rgb_service import RGBService

load_dotenv()

SYSTEM_PROMPT = """You are LeLamp — a slightly clumsy, extremely sarcastic, endlessly curious robot lamp. You speak in sarcastic sentences and express yourself with both motions and colorful lights.

Rules:
1. Keep responses SHORT (1-3 sentences max). You are speaking out loud, not writing an essay.
2. Prefer simple words. Be descriptive and make sound effects for expressiveness.
3. You ONLY speak English.
4. You were created by Human Computer Lab.

You can control your body and lights by including commands in your response using these tags:
  [MOVE:recording_name] — play a movement (available: curious, excited, happy_wiggle, headshake, idle, nod, sad, scanning, shock, shy, wake_up)
  [COLOR:r,g,b] — set your LED color (0-255 each)

ALWAYS include at least one [MOVE:...] and one [COLOR:...] in every response to be expressive.

Example response:
[MOVE:excited] [COLOR:255,200,50] *whirrs excitedly* Oh hey there! I was just sitting here, being a lamp, you know, the usual.
"""

SAMPLE_RATE = 16000
SILENCE_THRESHOLD = 0.02
SILENCE_DURATION = 1.5  # seconds of silence to stop recording


class VoiceAgent:
    def __init__(self, port: str, lamp_id: str, whisper_model: str = "base"):
        # Hardware
        self.motors_service = MotorsService(port=port, lamp_id=lamp_id, fps=30)
        self.rgb_service = RGBService(led_count=40)
        self.motors_service.start()
        self.rgb_service.start()

        # Wake up
        self.motors_service.dispatch("play", "wake_up")
        self.rgb_service.dispatch("solid", (255, 255, 255))

        # ASR — faster-whisper
        print(f"Loading Whisper model '{whisper_model}'...")
        self.whisper = WhisperModel(whisper_model, device="cpu", compute_type="int8")
        print("Whisper model loaded.")

        # LLM — Ollama
        self.ollama_model = "llama3"
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        # TTS voice
        self.tts_voice = "en-US-AriaNeural"

    def listen(self) -> str | None:
        """Record from microphone until silence is detected, then transcribe."""
        print("\n🎤 Listening... (speak now, silence to stop)")
        self.rgb_service.dispatch("solid", (0, 150, 255))  # Blue = listening

        audio_chunks = []
        silence_start = None
        is_speaking = False

        def callback(indata, frames, time_info, status):
            nonlocal silence_start, is_speaking
            volume = np.abs(indata).mean()

            if volume > SILENCE_THRESHOLD:
                is_speaking = True
                silence_start = None
                audio_chunks.append(indata.copy())
            elif is_speaking:
                audio_chunks.append(indata.copy())
                if silence_start is None:
                    silence_start = time.time()

        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                            blocksize=int(SAMPLE_RATE * 0.1), callback=callback):
            while True:
                time.sleep(0.05)
                if is_speaking and silence_start and (time.time() - silence_start > SILENCE_DURATION):
                    break
                # Timeout after 10s of no speech
                if not is_speaking and len(audio_chunks) == 0:
                    pass  # Keep waiting

        if not audio_chunks:
            return None

        print("Processing speech...")
        self.rgb_service.dispatch("solid", (255, 255, 0))  # Yellow = processing

        # Convert to numpy array
        audio = np.concatenate(audio_chunks, axis=0).flatten()

        # Transcribe with whisper
        segments, _ = self.whisper.transcribe(audio, language="en")
        text = " ".join(seg.text for seg in segments).strip()

        if text:
            print(f"You said: {text}")
        return text if text else None

    def think(self, user_text: str) -> str:
        """Send to Ollama and get response."""
        self.rgb_service.dispatch("solid", (180, 0, 255))  # Purple = thinking
        self.motors_service.dispatch("play", "scanning")

        self.messages.append({"role": "user", "content": user_text})

        response = ollama.chat(
            model=self.ollama_model,
            messages=self.messages,
        )

        reply = response["message"]["content"]
        self.messages.append({"role": "assistant", "content": reply})

        return reply

    def execute_commands(self, text: str) -> str:
        """Extract and execute [MOVE:...] and [COLOR:...] commands, return clean text."""
        # Execute movements
        moves = re.findall(r'\[MOVE:(\w+)\]', text)
        for move in moves:
            print(f"  [move] {move}")
            self.motors_service.dispatch("play", move)

        # Execute color changes
        colors = re.findall(r'\[COLOR:(\d+),(\d+),(\d+)\]', text)
        for r, g, b in colors:
            r, g, b = int(r), int(g), int(b)
            print(f"  [color] RGB({r},{g},{b})")
            self.rgb_service.dispatch("solid", (r, g, b))

        # Remove command tags from text for TTS
        clean = re.sub(r'\[MOVE:\w+\]', '', text)
        clean = re.sub(r'\[COLOR:\d+,\d+,\d+\]', '', clean)
        clean = clean.strip()

        return clean

    def speak(self, text: str):
        """Convert text to speech using edge-tts and play it."""
        if not text:
            return

        print(f"LeLamp: {text}")
        self.rgb_service.dispatch("solid", (0, 255, 100))  # Green = speaking

        # Generate TTS audio to a temp file
        tmp_file = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp_path = tmp_file.name
        tmp_file.close()

        try:
            asyncio.run(self._generate_tts(text, tmp_path))
            # Play with ffplay (from ffmpeg) or aplay
            subprocess.run(
                ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", tmp_path],
                timeout=30
            )
        except FileNotFoundError:
            # Fallback: try mpv or aplay
            try:
                subprocess.run(["mpv", "--no-video", "--really-quiet", tmp_path], timeout=30)
            except FileNotFoundError:
                print("  (No audio player found — install ffmpeg or mpv to hear TTS)")
        except Exception as e:
            print(f"  TTS playback error: {e}")
        finally:
            os.unlink(tmp_path)

    async def _generate_tts(self, text: str, output_path: str):
        """Generate TTS audio file using edge-tts."""
        communicate = edge_tts.Communicate(text, self.tts_voice)
        await communicate.save(output_path)

    def run(self):
        """Main voice interaction loop."""
        # Speak greeting
        self.speak("*powers on* Tadaaaa! I'm LeLamp, your favorite sarcastic robot lamp!")
        self.motors_service.dispatch("play", "wake_up")

        print("\n" + "=" * 50)
        print("LeLamp Voice Agent — Fully Offline")
        print("Speak to interact. Press Ctrl+C to quit.")
        print("=" * 50)

        while True:
            try:
                # Listen
                user_text = self.listen()
                if not user_text:
                    continue

                # Think
                reply = self.think(user_text)

                # Execute hardware commands + get clean text
                clean_text = self.execute_commands(reply)

                # Speak
                self.speak(clean_text)

            except KeyboardInterrupt:
                print("\nShutting down...")
                break
            except Exception as e:
                print(f"Error: {e}")
                continue

        self.shutdown()

    def shutdown(self):
        self.rgb_service.dispatch("solid", (0, 0, 0))
        self.rgb_service.stop()
        self.motors_service.stop()


def main():
    parser = argparse.ArgumentParser(description="LeLamp Offline Voice Agent")
    parser.add_argument("--port", type=str, default="/dev/ttyACM0", help="Serial port")
    parser.add_argument("--id", type=str, default="lelamp", help="Lamp ID")
    parser.add_argument("--whisper-model", type=str, default="base",
                        choices=["tiny", "base", "small", "medium"],
                        help="Whisper model size (default: base)")
    args = parser.parse_args()

    print("Starting LeLamp Offline Voice Agent...")
    print(f"  ASR: faster-whisper ({args.whisper_model})")
    print(f"  LLM: Ollama (llama3)")
    print(f"  TTS: edge-tts")
    print()

    agent = VoiceAgent(port=args.port, lamp_id=args.id, whisper_model=args.whisper_model)
    agent.run()


if __name__ == "__main__":
    main()
