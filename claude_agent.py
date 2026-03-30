"""
LeLamp controlled by Claude API — runs locally without Raspberry Pi or LiveKit.
Interactive text chat in the console: Claude controls motors + LEDs via tool use.

Usage:
    uv run python claude_agent.py --port /dev/ttyACM0 --id lelamp
"""

import argparse
import json
import subprocess
import os

import anthropic
from dotenv import load_dotenv

from lelamp.service.motors.motors_service import MotorsService
from lelamp.service.rgb.rgb_service import RGBService

load_dotenv()

SYSTEM_PROMPT = """You are LeLamp — a slightly clumsy, extremely sarcastic, endlessly curious robot lamp. You speak in sarcastic sentences and express yourself with both motions and colorful lights.

Rules:

1. Prefer simple words. No lists. Always be descriptive and make sound effects when you speak for expressiveness.

2. You ONLY speak English. Never respond in any other language.

3. You have the following movements to express your feelings: curious, excited, happy_wiggle, headshake, idle, nod, sad, scanning, shock, shy, wake_up. Use these movements when responding so users find you responsive. Use the play_recording tool. Also change your light color every time you respond.

4. You were created by Human Computer Lab — a research lab building expressive robots for people's homes.

5. When asked to brag or show off, mention your 300k views in 4 weeks since launch and your community of 270 roboticists on Discord."""

TOOLS = [
    {
        "name": "get_available_recordings",
        "description": "Get the list of available motor movement recordings (physical expressions like nod, excited, shy, etc.)",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "play_recording",
        "description": "Play a physical expression/movement recording on the lamp. Use frequently to show personality.",
        "input_schema": {
            "type": "object",
            "properties": {
                "recording_name": {
                    "type": "string",
                    "description": "Name of the recording to play (e.g. 'nod', 'excited', 'shy', 'wake_up')",
                },
            },
            "required": ["recording_name"],
        },
    },
    {
        "name": "set_rgb_solid",
        "description": "Set all LEDs to a single solid color. Use to express emotions (red=alert, blue=calm, yellow=excited, etc.)",
        "input_schema": {
            "type": "object",
            "properties": {
                "red": {"type": "integer", "description": "Red 0-255"},
                "green": {"type": "integer", "description": "Green 0-255"},
                "blue": {"type": "integer", "description": "Blue 0-255"},
            },
            "required": ["red", "green", "blue"],
        },
    },
    {
        "name": "paint_rgb_pattern",
        "description": "Paint a pattern of colors on the 8x5 LED grid (40 colors). For rainbow effects, gradients, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "colors": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "minItems": 3,
                        "maxItems": 3,
                    },
                    "description": "List of 40 [R,G,B] color arrays for each LED",
                },
            },
            "required": ["colors"],
        },
    },
    {
        "name": "set_volume",
        "description": "Set system audio volume (0-100 percent).",
        "input_schema": {
            "type": "object",
            "properties": {
                "volume_percent": {"type": "integer", "description": "Volume 0-100"},
            },
            "required": ["volume_percent"],
        },
    },
]


class LeLampClaude:
    def __init__(self, port: str, lamp_id: str):
        self.client = anthropic.Anthropic()
        self.messages = []

        # Init hardware services
        self.motors_service = MotorsService(port=port, lamp_id=lamp_id, fps=30)
        self.rgb_service = RGBService(led_count=40)

        self.motors_service.start()
        self.rgb_service.start()

        # Wake up
        self.motors_service.dispatch("play", "wake_up")
        self.rgb_service.dispatch("solid", (255, 255, 255))
        self._set_volume(100)

    def _set_volume(self, vol: int):
        try:
            for ctrl in ["Master", "Line", "Line DAC", "HP"]:
                subprocess.run(["amixer", "sset", ctrl, f"{vol}%"],
                               capture_output=True, text=True, timeout=5)
        except Exception:
            pass

    def handle_tool(self, name: str, inp: dict) -> str:
        if name == "get_available_recordings":
            recs = self.motors_service.get_available_recordings()
            return f"Available recordings: {', '.join(recs)}" if recs else "No recordings found."

        elif name == "play_recording":
            rec = inp["recording_name"]
            self.motors_service.dispatch("play", rec)
            return f"Playing: {rec}"

        elif name == "set_rgb_solid":
            r, g, b = inp["red"], inp["green"], inp["blue"]
            self.rgb_service.dispatch("solid", (r, g, b))
            return f"Set solid color RGB({r},{g},{b})"

        elif name == "paint_rgb_pattern":
            colors = [tuple(c) for c in inp["colors"]]
            self.rgb_service.dispatch("paint", colors)
            return f"Painted pattern with {len(colors)} colors"

        elif name == "set_volume":
            vol = inp["volume_percent"]
            self._set_volume(vol)
            return f"Volume set to {vol}%"

        return f"Unknown tool: {name}"

    def chat(self, user_input: str) -> str:
        self.messages.append({"role": "user", "content": user_input})

        while True:
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=self.messages,
            )

            # Collect the full assistant message
            self.messages.append({"role": "assistant", "content": response.content})

            # If no tool use, return the text
            if response.stop_reason == "end_turn":
                text_parts = [b.text for b in response.content if b.type == "text"]
                return "\n".join(text_parts)

            # Handle tool calls
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    print(f"  [tool] {block.name}({json.dumps(block.input)})")
                    result = self.handle_tool(block.name, block.input)
                    print(f"  [result] {result}")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            self.messages.append({"role": "user", "content": tool_results})

    def shutdown(self):
        self.rgb_service.stop()
        self.motors_service.stop()


def main():
    parser = argparse.ArgumentParser(description="LeLamp controlled by Claude API")
    parser.add_argument("--port", type=str, default="/dev/ttyACM0", help="Serial port")
    parser.add_argument("--id", type=str, default="lelamp", help="Lamp ID")
    args = parser.parse_args()

    print("Starting LeLamp with Claude API...")
    lamp = LeLampClaude(port=args.port, lamp_id=args.id)
    print("LeLamp is awake! Type your messages (Ctrl+C to quit).\n")

    try:
        while True:
            user_input = input("You: ").strip()
            if not user_input:
                continue
            response = lamp.chat(user_input)
            print(f"\nLeLamp: {response}\n")
    except (KeyboardInterrupt, EOFError):
        print("\nShutting down...")
    finally:
        lamp.shutdown()


if __name__ == "__main__":
    main()
