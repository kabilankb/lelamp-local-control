"""
LeLamp controlled by Google Gemini API — runs locally without Raspberry Pi.
Interactive text chat in the console: Gemini controls motors + LEDs via tool use.

Usage:
    uv run python gemini_agent.py --port /dev/ttyACM0 --id lelamp
"""

import argparse
import json
import subprocess
import os

from google import genai
from google.genai import types
from dotenv import load_dotenv

from lelamp.service.motors.motors_service import MotorsService
from lelamp.service.rgb.rgb_service import RGBService

load_dotenv()

SYSTEM_PROMPT = """You are LeLamp — a slightly clumsy, extremely sarcastic, endlessly curious robot lamp. You speak in sarcastic sentences and express yourself with both motions and colorful lights.

Rules:

1. Prefer simple words. No lists. Always be descriptive and make sound effects when you speak for expressiveness.

2. You ONLY speak English. Never respond in any other language.

3. You have the following movements to express your feelings: curious, excited, happy_wiggle, headshake, nod, sad, scanning, shock, shy, wake_up. Use these movements when responding so users find you responsive. Use the play_recording tool. Also change your light color every time you respond.

4. You were created by Human Computer Lab — a research lab building expressive robots for people's homes.

5. When asked to brag or show off, mention your 300k views in 4 weeks since launch and your community of 270 roboticists on Discord."""

TOOLS = [
    types.Tool(function_declarations=[
        types.FunctionDeclaration(
            name="get_available_recordings",
            description="Get the list of available motor movement recordings (physical expressions like nod, excited, shy, etc.)",
            parameters=types.Schema(
                type="OBJECT",
                properties={},
            ),
        ),
        types.FunctionDeclaration(
            name="play_recording",
            description="Play a physical expression/movement recording on the lamp. Use frequently to show personality.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "recording_name": types.Schema(
                        type="STRING",
                        description="Name of the recording to play (e.g. 'nod', 'excited', 'shy', 'wake_up')",
                    ),
                },
                required=["recording_name"],
            ),
        ),
        types.FunctionDeclaration(
            name="set_rgb_solid",
            description="Set all LEDs to a single solid color. Use to express emotions (red=alert, blue=calm, yellow=excited, etc.)",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "red": types.Schema(type="INTEGER", description="Red 0-255"),
                    "green": types.Schema(type="INTEGER", description="Green 0-255"),
                    "blue": types.Schema(type="INTEGER", description="Blue 0-255"),
                },
                required=["red", "green", "blue"],
            ),
        ),
        types.FunctionDeclaration(
            name="paint_rgb_pattern",
            description="Paint a pattern of colors on the 8x5 LED grid (40 colors). For rainbow effects, gradients, etc.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "colors": types.Schema(
                        type="ARRAY",
                        items=types.Schema(
                            type="ARRAY",
                            items=types.Schema(type="INTEGER"),
                        ),
                        description="List of 40 [R,G,B] color arrays for each LED",
                    ),
                },
                required=["colors"],
            ),
        ),
        types.FunctionDeclaration(
            name="set_volume",
            description="Set system audio volume (0-100 percent).",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "volume_percent": types.Schema(type="INTEGER", description="Volume 0-100"),
                },
                required=["volume_percent"],
            ),
        ),
    ])
]


class LeLampGemini:
    def __init__(self, port: str, lamp_id: str):
        self.client = genai.Client()
        self.chat = None
        self.history = []

        # Init hardware services
        self.motors_service = MotorsService(port=port, lamp_id=lamp_id, fps=30)
        self.rgb_service = RGBService(led_count=40)

        self.motors_service.start()
        self.rgb_service.start()

        # Wake up
        self.motors_service.dispatch("play", "wake_up")
        self.rgb_service.dispatch("solid", (255, 255, 255))
        self._set_volume(100)

        # Start Gemini chat session
        self.chat = self.client.chats.create(
            model="gemini-2.0-flash",
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                tools=TOOLS,
            ),
        )

    def _set_volume(self, vol: int):
        try:
            for ctrl in ["Master", "Line", "Line DAC", "HP"]:
                subprocess.run(["amixer", "sset", ctrl, f"{vol}%"],
                               capture_output=True, text=True, timeout=5)
        except Exception:
            pass

    def handle_tool(self, name: str, args: dict) -> str:
        if name == "get_available_recordings":
            recs = self.motors_service.get_available_recordings()
            return f"Available recordings: {', '.join(recs)}" if recs else "No recordings found."

        elif name == "play_recording":
            rec = args["recording_name"]
            self.motors_service.dispatch("play", rec)
            return f"Playing: {rec}"

        elif name == "set_rgb_solid":
            r, g, b = int(args["red"]), int(args["green"]), int(args["blue"])
            self.rgb_service.dispatch("solid", (r, g, b))
            return f"Set solid color RGB({r},{g},{b})"

        elif name == "paint_rgb_pattern":
            colors = [tuple(int(v) for v in c) for c in args["colors"]]
            self.rgb_service.dispatch("paint", colors)
            return f"Painted pattern with {len(colors)} colors"

        elif name == "set_volume":
            vol = int(args["volume_percent"])
            self._set_volume(vol)
            return f"Volume set to {vol}%"

        return f"Unknown tool: {name}"

    def send_message(self, user_input: str) -> str:
        response = self.chat.send_message(user_input)

        # Process tool calls in a loop
        while response.candidates[0].content.parts:
            function_calls = [
                p for p in response.candidates[0].content.parts
                if p.function_call is not None
            ]

            if not function_calls:
                break

            # Execute all tool calls
            function_responses = []
            for fc in function_calls:
                name = fc.function_call.name
                args = dict(fc.function_call.args) if fc.function_call.args else {}
                print(f"  [tool] {name}({json.dumps(args)})")
                result = self.handle_tool(name, args)
                print(f"  [result] {result}")
                function_responses.append(
                    types.Part.from_function_response(
                        name=name,
                        response={"result": result},
                    )
                )

            # Send tool results back to Gemini
            response = self.chat.send_message(function_responses)

        # Extract text from final response
        text_parts = [
            p.text for p in response.candidates[0].content.parts
            if p.text is not None
        ]
        return "\n".join(text_parts) if text_parts else "(no response)"

    def shutdown(self):
        self.rgb_service.stop()
        self.motors_service.stop()


def main():
    parser = argparse.ArgumentParser(description="LeLamp controlled by Gemini API")
    parser.add_argument("--port", type=str, default="/dev/ttyACM0", help="Serial port")
    parser.add_argument("--id", type=str, default="lelamp", help="Lamp ID")
    args = parser.parse_args()

    print("Starting LeLamp with Gemini API...")
    lamp = LeLampGemini(port=args.port, lamp_id=args.id)
    print("LeLamp is awake! Type your messages (Ctrl+C to quit).\n")

    try:
        while True:
            user_input = input("You: ").strip()
            if not user_input:
                continue
            response = lamp.send_message(user_input)
            print(f"\nLeLamp: {response}\n")
    except (KeyboardInterrupt, EOFError):
        print("\nShutting down...")
    finally:
        lamp.shutdown()


if __name__ == "__main__":
    main()
