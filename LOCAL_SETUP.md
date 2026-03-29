# LeLamp Local Setup Guide (Without Raspberry Pi)

This guide explains how to run the LeLamp robot on a local Linux system (desktop/laptop) without a Raspberry Pi. The servo motors connect directly via USB, and the RGB LEDs are simulated in the terminal.

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
- [Available Recordings](#available-recordings)
- [Troubleshooting](#troubleshooting)

---

## Architecture Overview

```
┌──────────────────────────────────────────────────┐
│                 Local Linux PC                    │
│                                                   │
│  ┌─────────────┐   ┌──────────────┐              │
│  │ Claude API   │   │ LiveKit +    │              │
│  │ (text chat)  │   │ OpenAI       │              │
│  │ claude_agent │   │ (voice chat) │              │
│  │    .py       │   │ main.py      │              │
│  └──────┬───────┘   └──────┬───────┘              │
│         │                  │                      │
│         └────────┬─────────┘                      │
│                  │                                │
│  ┌───────────────▼────────────────┐               │
│  │         Service Layer          │               │
│  │  ┌──────────┐  ┌───────────┐  │               │
│  │  │  Motors   │  │    RGB    │  │               │
│  │  │ Service   │  │  Service  │  │               │
│  │  └─────┬────┘  └─────┬────┘  │               │
│  └────────┼──────────────┼──────┘               │
│           │              │                        │
│    USB Serial        Terminal                     │
│    /dev/ttyACM0      Simulator                    │
│           │          (colored                     │
│           │           blocks)                     │
└───────────┼──────────────────────────────────────┘
            │
    ┌───────▼────────┐
    │ Feetech Servo  │
    │ Controller     │
    │ Board (USB)    │
    ├────────────────┤
    │ STS3215 Servos │
    │ x5 (daisy      │
    │    chain)      │
    └────────────────┘
```

## What Changed vs. Original

| Component | Original (Raspberry Pi) | Local (This Setup) |
|-----------|------------------------|-------------------|
| Servo Motors | USB serial via Pi | USB serial directly to PC |
| RGB LEDs | WS281x via Pi GPIO | Terminal simulator (colored blocks) |
| Volume Control | `sudo -u pi amixer` | Standard `amixer` |
| Voice Agent | LiveKit + OpenAI only | Claude API (text) or LiveKit + OpenAI (voice) |
| NeoPixel lib | `rpi-ws281x` required | Auto-detected, falls back to software |
| Python | System Python on Pi | Python 3.12 via `uv` |

### Modified Files

- `lelamp/service/rgb/rgb_service.py` — Auto-detects Pi hardware; uses console simulator on local systems
- `main.py` — Volume control uses standard Linux `amixer` (no `sudo -u pi`)
- `smooth_animation.py` — Same volume control fix
- `pyproject.toml` — Added `anthropic` SDK dependency

### New Files

- `claude_agent.py` — Claude API-powered text agent (no LiveKit/OpenAI needed)
- `LOCAL_SETUP.md` — This document

---

## Prerequisites

- **OS**: Linux (Ubuntu/Debian recommended)
- **Python**: 3.12+ (installed automatically by `uv`)
- **USB port**: For Feetech servo controller board
- **System packages**:
  ```bash
  sudo apt-get install -y portaudio19-dev alsa-utils
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

### Option 1: Claude API Agent (Text Chat — Recommended for Local)

No LiveKit or OpenAI account needed. Just an Anthropic API key.

**Setup:**

Create `.env` in the project root:
```
ANTHROPIC_API_KEY=sk-ant-...
```

**Run:**
```bash
uv run python claude_agent.py --port /dev/ttyACM0 --id lelamp
```

**What happens:**
- Interactive text chat in the terminal
- Claude automatically calls tools to move motors and change LED colors
- Type messages, Claude responds with text + physical expressions

```
You: hey there!
  [tool] play_recording({"recording_name": "excited"})
  [result] Playing: excited
  [tool] set_rgb_solid({"red": 255, "green": 200, "blue": 50})
  [result] Set solid color RGB(255,200,50)

LeLamp: *whirrs excitedly* Oh FINALLY, someone talks to me!
```

### Option 2: LiveKit + OpenAI Voice Agent (Original)

Requires LiveKit and OpenAI accounts.

**Setup:**

Create `.env`:
```
OPENAI_API_KEY=sk-...
LIVEKIT_URL=wss://...
LIVEKIT_API_KEY=...
LIVEKIT_API_SECRET=...
```

Get LiveKit secrets:
```bash
lk app env -w
cat .env.local
```

**Run:**
```bash
# Discrete animation mode
uv run main.py console

# Smooth animation mode
uv run smooth_animation.py console
```

---

## Available Recordings

Pre-loaded expressive movements:

| Recording | Description |
|-----------|-------------|
| `curious` | Inquisitive head tilt |
| `excited` | Energetic bouncing motion |
| `happy_wiggle` | Joyful side-to-side wiggle |
| `headshake` | Disapproving head shake (no) |
| `idle` | Subtle breathing/resting motion (loops) |
| `nod` | Agreeing nod (yes) |
| `sad` | Drooping, disappointed posture |
| `scanning` | Looking around the room |
| `shock` | Startled jump reaction |
| `shy` | Bashful ducking motion |
| `wake_up` | Power-on startup sequence |

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

### Claude API Credit Error

```
anthropic.BadRequestError: Your credit balance is too low
```

Add credits at [console.anthropic.com/settings/billing](https://console.anthropic.com/settings/billing).

### Motor Shaking/Vibrating

The PID values are set in `lelamp_follower.py` (P=16, I=0, D=32). If motors shake:
- Check power supply voltage (should be stable 6-7.4V)
- Verify calibration is complete
- Reduce `max_relative_target` in the config to limit movement speed

### Extended Usage Warning

Running servos continuously for >1 hour can overheat the motors. Allow cooling breaks during long sessions.
