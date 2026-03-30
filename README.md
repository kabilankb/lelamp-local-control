# LeLamp Runtime

![](./assets/images/Banner.png)

This repository holds the code for controlling LeLamp — an open source robot lamp based on [Apple's Elegnt](https://machinelearning.apple.com/research/elegnt-expressive-functional-movement), made by [Human Computer Lab](https://www.humancomputerlab.com/). Runs fully on a local Linux system (desktop/laptop) without a Raspberry Pi. The servo motors connect directly via USB, and the RGB LEDs are simulated in the terminal. Includes web control panel with hands-free voice interaction.

[LeLamp](https://github.com/humancomputerlab/LeLamp)

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [What Changed vs. Original](#what-changed-vs-original)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Hardware Wiring](#hardware-wiring)
- [Motor Setup](#motor-setup)
- [Calibration](#calibration)
- [Testing](#testing)
- [Recording & Replaying Movements](#recording--replaying-movements)
- [Running the Agent](#running-the-agent)
- [Web Control Panel](#web-control-panel)
- [Available Recordings](#available-recordings)
- [Start upon Boot](#start-upon-boot)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Local Linux PC                        │
│                                                          │
│  ┌────────────┐ ┌────────────┐ ┌──────────┐ ┌────────┐ │
│  │ Web Panel  │ │  Voice     │ │ Claude   │ │ Gemini │ │
│  │ web_agent  │ │  Agent     │ │ Agent    │ │ Agent  │ │
│  │   .py      │ │ voice_agent│ │ claude_  │ │ gemini_│ │
│  │ + ASR/TTS  │ │   .py      │ │ agent.py │ │ agent  │ │
│  └─────┬──────┘ └─────┬──────┘ └────┬─────┘ └───┬────┘ │
│        │              │             │            │      │
│        └──────┬───────┴─────────────┴────────────┘      │
│               │                                          │
│  ┌────────────▼─────────────────┐                        │
│  │       Service Layer          │                        │
│  │  ┌──────────┐ ┌───────────┐  │    ┌──────────────┐   │
│  │  │  Motors   │ │    RGB    │  │    │   Ollama     │   │
│  │  │ Service   │ │  Service  │  │    │  (llama3)    │   │
│  │  └─────┬────┘ └─────┬────┘  │    └──────────────┘   │
│  └────────┼─────────────┼──────┘                        │
│           │             │                                │
│     USB Serial      Terminal                             │
│    /dev/ttyACM0     Simulator                            │
│           │                                              │
└───────────┼──────────────────────────────────────────────┘
            │
    ┌───────▼────────┐
    │ Feetech Servo  │
    │ Controller USB │
    │ + STS3215 x5   │
    └────────────────┘
```

## Project Structure

```
lelamp_runtime/
├── main.py                 # LiveKit voice agent (Raspberry Pi)
├── smooth_animation.py     # LiveKit agent with smooth animations
├── claude_agent.py         # Claude API text agent (local)
├── gemini_agent.py         # Gemini API text agent (local)
├── voice_agent.py          # Offline voice agent (Whisper + Ollama + edge-tts)
├── web_agent.py            # Web control panel (Flask + Ollama)
├── templates/              # Web UI templates
├── pyproject.toml          # Project configuration and dependencies
├── lelamp/                 # Core package
│   ├── setup_motors.py     # Motor configuration and setup
│   ├── calibrate.py        # Motor calibration utilities
│   ├── list_recordings.py  # List all recorded motor movements
│   ├── record.py           # Movement recording functionality
│   ├── replay.py           # Movement replay functionality
│   ├── follower/           # Follower mode functionality
│   ├── leader/             # Leader mode functionality
│   ├── service/            # Motor and RGB service layer
│   └── test/               # Hardware testing modules
└── uv.lock                 # Dependency lock file
```

## What Changed vs. Original

| Component | Original (Raspberry Pi) | Local (This Setup) |
|-----------|------------------------|-------------------|
| Servo Motors | USB serial via Pi | USB serial directly to PC |
| RGB LEDs | WS281x via Pi GPIO | Terminal simulator (colored blocks) |
| Volume Control | `sudo -u pi amixer` | Standard `amixer` |
| Voice Agent | LiveKit + OpenAI only | Browser ASR/TTS + Ollama (free) |
| NeoPixel lib | `rpi-ws281x` required | Auto-detected, falls back to software |
| Python | System Python on Pi | Python 3.12 via `uv` |
| Web UI | None | Full control panel at localhost:5000 |

### Modified Files

- `lelamp/service/rgb/rgb_service.py` — Auto-detects Pi hardware; uses console simulator on local systems
- `main.py` — Volume control uses standard Linux `amixer` (no `sudo -u pi`)
- `smooth_animation.py` — Same volume control fix
- `pyproject.toml` — Added `anthropic`, `google-genai`, `ollama`, `flask-socketio`, `faster-whisper`, `edge-tts` dependencies

### New Files

- `web_agent.py` — Web control panel with chat, LED viz, voice ASR/TTS (Ollama)
- `voice_agent.py` — Offline terminal voice agent (Whisper + Ollama + Edge TTS)
- `claude_agent.py` — Claude API text agent
- `gemini_agent.py` — Gemini API text agent
- `templates/index.html` — Web control panel UI
- `templates/landing.html` — Landing page

---

## Prerequisites

- **OS**: Linux (Ubuntu/Debian recommended)
- **Python**: 3.12+ (installed automatically by `uv`)
- **USB port**: For Feetech servo controller board
- **System packages**:
  ```bash
  sudo apt-get install -y portaudio19-dev alsa-utils
  ```
- **Ollama** (for free local LLM):
  ```bash
  curl -fsSL https://ollama.com/install.sh | sh
  ollama pull llama3
  ```

### Hardware Required

- Feetech STS3215 servo motors x5
- Feetech servo controller board (USB interface)
- USB cable (controller board to PC)
- Assembled LeLamp body (see [main LeLamp repo](https://github.com/humancomputerlab/LeLamp))

---

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/humancomputerlab/lelamp_runtime.git
cd lelamp_runtime

# 2. Install uv (if not installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 3. Install Python 3.12 (if needed)
uv python install 3.12

# 4. Install all dependencies (NO --extra hardware needed)
uv sync

# If slow, use:
# UV_CONCURRENT_DOWNLOADS=1 uv sync

# If LFS issues:
# GIT_LFS_SKIP_SMUDGE=1 uv sync
```

### Dependencies

The runtime includes several key dependencies:

- **feetech-servo-sdk**: For servo motor control
- **lerobot**: Robotics framework integration
- **ollama**: Local LLM integration
- **flask-socketio**: Web control panel
- **faster-whisper**: Local speech recognition
- **edge-tts**: Text-to-speech
- **anthropic**: Claude API agent
- **google-genai**: Gemini API agent
- **numpy**: Mathematical operations
- **sounddevice**: Audio input/output

---

## Hardware Wiring

Connect the Feetech servo controller board to your PC via USB. The servos connect in a daisy chain to the controller board.

### Find Your Serial Port

```bash
uv run lerobot-find-port
```

Common ports on Linux:
- `/dev/ttyACM0` — most common for Feetech USB boards
- `/dev/ttyACM1` — if another device is on ACM0
- `/dev/ttyUSB0` — for USB-to-serial adapters

### Permission Fix

If you get a "Permission denied" error on the serial port:

```bash
sudo usermod -a -G dialout $USER
# Then log out and log back in
```

---

## Motor Setup

This assigns a unique ID (1-5) to each servo motor. **Only one motor should be connected at a time.**

```bash
uv run -m lelamp.setup_motors --id lelamp --port /dev/ttyACM0
```

The command will prompt you to connect each motor one at a time, in this order:

| Step | Motor | ID | Physical Joint |
|------|-------|----|----------------|
| 1 | `wrist_pitch` | 5 | Lamp head tilt (up/down) |
| 2 | `wrist_roll` | 4 | Lamp head rotation |
| 3 | `elbow_pitch` | 3 | Middle joint bend |
| 4 | `base_pitch` | 2 | Base tilt (forward/back) |
| 5 | `base_yaw` | 1 | Base rotation (left/right) |

**Procedure for each step:**
1. Disconnect all other motors from the controller board
2. Connect ONLY the motor listed in the prompt
3. Press Enter
4. Wait for confirmation, then move to next motor

After all 5 motors are set up, **reconnect them all** in the daisy chain.

---

## Calibration

Calibration teaches the system each motor's range of motion.

```bash
uv run -m lelamp.calibrate --id lelamp --port /dev/ttyACM0
```

### Calibration Process

1. **Mid-position**: Move the lamp to the middle of its range of motion, press Enter
2. **Range recording**: Move each joint through its full range of motion, press Enter when done
3. Repeat for both follower and leader modes

### Calibrate Only One Mode

```bash
# Follower only
uv run -m lelamp.calibrate --id lelamp --port /dev/ttyACM0 --follower-only

# Leader only
uv run -m lelamp.calibrate --id lelamp --port /dev/ttyACM0 --leader-only
```

Calibration data is saved automatically and reused on future connections.

---

## Testing

### Test Motors

```bash
uv run -m lelamp.test.test_motors --id lelamp --port /dev/ttyACM0
```

Plays the first available recording to verify motor control.

### Test RGB LEDs

```bash
uv run -m lelamp.test.test_rgb
```

On local systems, this outputs colored blocks to the terminal:
```
[LED] ████████████████████████████████████████   (red)
[LED] ████████████████████████████████████████   (green)
[LED] ████████████████████████████████████████   (blue)
[LED] █████████████████████████████████████████  (pattern)
```

### Test Audio

```bash
uv run -m lelamp.test.test_audio
```

---

## Recording & Replaying Movements

### Record a Movement

Put the lamp in recording mode, physically move it, then press Ctrl+C to stop:

```bash
uv run -m lelamp.record --id lelamp --port /dev/ttyACM0 --name my_movement
```

Options:
- `--fps 30` — Recording frame rate (default: 30)

### Replay a Movement

```bash
uv run -m lelamp.replay --id lelamp --port /dev/ttyACM0 --name my_movement
```

### List All Recordings

```bash
uv run -m lelamp.list_recordings --id lelamp
```

### Recording Format

Movements are stored as CSV files in `lelamp/recordings/`:

```
lelamp/recordings/
├── curious.csv
├── excited.csv
├── happy_wiggle.csv
├── headshake.csv
├── idle.csv
├── nod.csv
├── sad.csv
├── scanning.csv
├── shock.csv
├── shy.csv
└── wake_up.csv
```

Each CSV contains timestamped joint positions:
```csv
timestamp,base_yaw.pos,base_pitch.pos,elbow_pitch.pos,wrist_roll.pos,wrist_pitch.pos
1234567890.123,45.0,30.0,60.0,0.0,15.0
```

---

## Running the Agent

### Option 1: Web Control Panel (Recommended)

Full browser UI with hands-free voice chat, LED visualization, color control, and all 11 movement buttons. Uses Ollama (free, local).

```bash
uv run python web_agent.py --port /dev/ttyACM0 --id lelamp
```

Open **http://localhost:5000** in Chrome/Edge.

- **Landing page** at `/` — project overview
- **Control panel** at `/control` — chat, voice, LEDs, movements

Features:
- Always-on ASR — just speak, no button needed (uses Browser Web Speech API)
- TTS — LeLamp speaks back (Browser TTS or Edge TTS neural voice)
- Live 8x5 LED grid visualization
- RGB color picker with sliders
- All 11 movement buttons

### Option 2: Offline Voice Agent (Terminal)

Fully offline voice agent with Whisper ASR + Ollama + Edge TTS.

```bash
uv run python voice_agent.py --port /dev/ttyACM0 --id lelamp
```

Options:
```bash
# Faster but less accurate ASR
uv run python voice_agent.py --port /dev/ttyACM0 --whisper-model tiny

# More accurate ASR
uv run python voice_agent.py --port /dev/ttyACM0 --whisper-model small
```

Color indicators:
- Blue LED — Listening
- Yellow LED — Processing speech
- Purple LED — Thinking (Ollama)
- Green LED — Speaking

### Option 3: Claude API Agent (Text Chat)

Requires Anthropic API key with credits.

**Setup** — Add to `.env`:
```
ANTHROPIC_API_KEY=sk-ant-...
```

**Run:**
```bash
uv run python claude_agent.py --port /dev/ttyACM0 --id lelamp
```

### Option 4: Gemini API Agent (Text Chat)

Requires Google Gemini API key.

**Setup** — Add to `.env`:
```
GOOGLE_API_KEY=your-gemini-key
```

**Run:**
```bash
uv run python gemini_agent.py --port /dev/ttyACM0 --id lelamp
```

### Option 5: LiveKit + OpenAI Voice Agent (Original)

Requires LiveKit and OpenAI accounts.

**Setup** — Add to `.env`:
```
OPENAI_API_KEY=sk-...
LIVEKIT_URL=wss://...
LIVEKIT_API_KEY=...
LIVEKIT_API_SECRET=...
```

**Run:**
```bash
# Discrete animation mode
uv run main.py console

# Smooth animation mode
uv run smooth_animation.py console
```

### All Agents Summary

| Agent | Command | LLM | Voice | Cost |
|-------|---------|-----|-------|------|
| Web Panel | `uv run python web_agent.py` | Ollama (local) | Browser ASR + TTS | Free |
| Voice Agent | `uv run python voice_agent.py` | Ollama (local) | Whisper + Edge TTS | Free |
| Claude Agent | `uv run python claude_agent.py` | Claude Sonnet | Text only | Paid |
| Gemini Agent | `uv run python gemini_agent.py` | Gemini 2.0 Flash | Text only | Free tier |
| LiveKit Agent | `uv run main.py console` | OpenAI Realtime | Full voice | Paid |

---

## Web Control Panel

### Pages

| URL | Description |
|-----|-------------|
| `http://localhost:5000` | Landing page — project overview, features, setup guide |
| `http://localhost:5000/control` | Control panel — chat, voice, LEDs, movements |

### Control Panel Features

**Chat** — Type messages or speak hands-free. LeLamp responds with text, movements, and LED colors.

**Voice (ASR/TTS):**
- Always-on speech recognition — just speak (Chrome/Edge required)
- Auto-sends after 0.8s of silence
- TTS reads responses aloud (toggle on/off)
- Two TTS modes: Browser (fast) or Edge TTS (better quality, neural voice)
- ASR pauses during TTS to avoid hearing itself

**LED Display** — Live 8x5 grid showing current LED colors in real-time.

**Color Control** — RGB sliders (0-255) with preview and Apply button.

**Movements** — All 11 pre-loaded expressions as clickable buttons.

---

## Available Recordings

All 11 pre-loaded expressive movements:

| Recording | Emoji | Description |
|-----------|-------|-------------|
| `curious` | &#128064; | Inquisitive head tilt |
| `excited` | &#127881; | Energetic bouncing motion |
| `happy_wiggle` | &#128522; | Joyful side-to-side wiggle |
| `headshake` | &#128528; | Disapproving head shake (no) |
| `idle` | &#128564; | Subtle breathing/resting motion (loops) |
| `nod` | &#128077; | Agreeing nod (yes) |
| `sad` | &#128546; | Drooping, disappointed posture |
| `scanning` | &#128269; | Looking around the room |
| `shock` | &#9889; | Startled jump reaction |
| `shy` | &#128563; | Bashful ducking motion |
| `wake_up` | &#9728;&#65039; | Power-on startup sequence |

---

## Start upon Boot

If you want to start LeLamp's voice app upon booting, create a systemd service file:

```bash
sudo nano /etc/systemd/system/lelamp.service
```

Add this content:

```ini
[Unit]
Description=Lelamp Runtime Service
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/lelamp_runtime
ExecStart=/usr/bin/sudo uv run main.py console
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Then enable and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable lelamp.service
sudo systemctl start lelamp.service
```

For other service controls:

```bash
# Disable from starting on boot
sudo systemctl disable lelamp.service

# Stop the currently running service
sudo systemctl stop lelamp.service

# Check status (should show "disabled" and "inactive")
sudo systemctl status lelamp.service
```

Note: Boot time might vary with each run and extended usage (>1 hour) can burn the motors.

---

## Troubleshooting

### Serial Port Not Found

```
No such file or directory: '/dev/ttyACM0'
```

- Check USB cable connection
- Run `ls /dev/ttyACM* /dev/ttyUSB*` to find available ports
- Run `uv run lerobot-find-port` to auto-detect

### Permission Denied on Serial Port

```
PermissionError: [Errno 13] Permission denied: '/dev/ttyACM0'
```

```bash
sudo usermod -a -G dialout $USER
# Log out and back in
```

### Motor Not Responding

- Verify power supply to servo controller board
- Check daisy chain connections between servos
- Re-run motor setup: `uv run -m lelamp.setup_motors --id lelamp --port /dev/ttyACM0`
- Re-run calibration: `uv run -m lelamp.calibrate --id lelamp --port /dev/ttyACM0`

### RGB LEDs Show in Terminal Instead of Physical LEDs

This is expected on local systems without a Raspberry Pi. The `_SoftwareStrip` class in `rgb_service.py` prints colored Unicode blocks to simulate LED output. To use real WS281x LEDs, run on a Raspberry Pi with `uv sync --extra hardware`.

### Voice Not Working in Browser

- Use **Chrome or Edge** — Firefox does not support Web Speech API
- Allow microphone access when prompted
- Check that no other app is using the mic
- Falls back to server-side Whisper ASR if browser ASR is unavailable

### `ModuleNotFoundError: No module named 'lelamp'`

Make sure you're running from the project directory:
```bash
cd ~/lelamp_runtime
uv run -m lelamp.setup_motors ...
```

### `portaudio.h: No such file or directory`

```bash
sudo apt-get install -y portaudio19-dev
uv sync
```

### Ollama Not Running

```
ConnectionError: Failed to connect to Ollama
```

```bash
# Start Ollama service
ollama serve

# In another terminal, verify model is available
ollama list
```

### Claude API Credit Error

```
anthropic.BadRequestError: Your credit balance is too low
```

Add credits at [console.anthropic.com/settings/billing](https://console.anthropic.com/settings/billing).

### Gemini API Quota Exhausted

```
google.genai.errors.ClientError: 429 RESOURCE_EXHAUSTED
```

Wait for quota reset or enable billing at [aistudio.google.com](https://aistudio.google.com).

### Motor Shaking/Vibrating

The PID values are set in `lelamp_follower.py` (P=16, I=0, D=32). If motors shake:
- Check power supply voltage (should be stable 6-7.4V)
- Verify calibration is complete
- Reduce `max_relative_target` in the config to limit movement speed

### Extended Usage Warning

Running servos continuously for >1 hour can overheat the motors. Allow cooling breaks during long sessions.

---

## Contributing

This is an open-source project by Human Computer Lab. Contributions are welcome through the GitHub repository.

## Maintainers

Maintained by [Human Computer Lab](https://www.humancomputerlab.com).

## Acknowledgments & Sponsors

See [CONTRIBUTORS.md](./CONTRIBUTORS.md) for contributors and their roles.
See [SPONSORS.md](./SPONSORS.md) for sponsor thanks and how to support the project.

## License

Check the main [LeLamp repository](https://github.com/humancomputerlab/LeLamp) for licensing information.
