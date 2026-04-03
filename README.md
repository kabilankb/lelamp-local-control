# LeLamp Isaac Sim Simulation

Digital twin of the LeLamp robot in NVIDIA Isaac Sim, with real robot mirroring and recording playback.

![Image](https://github.com/user-attachments/assets/dd79863c-20dd-47eb-aee6-79ddae246f87)


## Architecture

```
LeLamp/simulation/
├── launch_isaacsim.py      # Main launcher (flat grid scene)
├── launch_kitchen.py       # Kitchen environment scene
├── add_diffuser_light.py   # Add DiskLight to lamp head
├── fix_usd.py              # Fix Chinese prim names + imu_site reference
├── test_loop.py            # Minimal Isaac Sim loop test
├── test_loop2.py           # Loop test with robot + articulation
├── robot.urdf              # Fixed URDF (ASCII names, joint_1-5)
├── robot.urdf.bak          # Original URDF backup
├── robot/                  # USD (imported from URDF)
│   ├── robot.usd           # Main robot USD (references sublayers)
│   └── configuration/
│       ├── robot_base.usd      # Link transforms, visuals, colliders
│       ├── robot_physics.usd   # Joint physics, drives, articulation
│       ├── robot_robot.usd     # Robot metadata
│       └── robot_sensor.usd    # Sensor config
├── assets/                 # STL meshes from Onshape
└── config.json             # Onshape export config
```

## Setup

### Prerequisites

- **Ubuntu 22.04+** (tested on 24.04)
- **NVIDIA GPU** with driver 535+ (for Isaac Sim rendering)
- **Conda** (Miniconda or Anaconda)
- **LeLamp hardware** (optional, only for mirror/record-sim modes)
  - Feetech STS3215 servos (x5)
  - USB servo controller board at `/dev/ttyACM0`
  - Calibrated via `uv run -m lelamp.calibrate`

### 1. Create Conda Environment

```bash
conda create -n leisaac python=3.11 -y
conda activate leisaac
```

### 2. Install Isaac Sim

```bash
pip install isaacsim==4.5.0
pip install isaacsim-extscache-physics isaacsim-extscache-kit isaacsim-extscache-kit-sdk
```

Verify installation:
```bash
python -c "from isaacsim import SimulationApp; print('Isaac Sim OK')"
```

### 3. Install scservo_sdk (for real robot modes)

```bash
pip install scservo-sdk
```

### 4. Clone and Navigate

```bash
git clone https://github.com/kabilankb/lelamp-local-control.git
cd lelamp-local-control
git checkout feature/isaacsim-digital-twin
cd simulation
```

### 5. Fix USD Assets (first time only)

```bash
python fix_usd.py
```

This renames Chinese-character prims and fixes broken IMU references in the robot USD files.

### 6. Add Diffuser Light (optional)

```bash
python add_diffuser_light.py
```

Adds a warm-white DiskLight to the lamp head for realistic lighting.

### 7. Verify

```bash
# Should open Isaac Sim window with robot on grid
python launch_isaacsim.py --mode sim-only --recording idle --loop
```

### Kitchen Environment (optional)

Download the kitchen scene USD and place it at:
```
~/Downloads/kitchen_with_orange/scene.usd
```

Then run:
```bash
python launch_kitchen.py --mode sim-only
```

### Calibration

The joint conversion values in the launch scripts are derived from:
```
~/.cache/huggingface/lerobot/calibration/robots/lelamp_follower/lelamp.json
```

If you recalibrate the real robot (`uv run -m lelamp.calibrate`), you'll need to recompute the scale/offset values. See the [simulation README](simulation/README.md) for the formula.

### USB Permissions (Linux)

If `/dev/ttyACM0` requires root access:
```bash
sudo usermod -a -G dialout $USER
# Log out and back in
```

## Quick Start

```bash
# Sim only — interactive recording picker
python launch_isaacsim.py --mode sim-only

# Sim only — specific recording, looped
python launch_isaacsim.py --mode sim-only --recording happy_wiggle --loop

# Mirror real robot (reads /dev/ttyACM0)
python launch_isaacsim.py --mode mirror --port /dev/ttyACM0

# Play recording on both real robot + sim
python launch_isaacsim.py --mode record-sim --port /dev/ttyACM0 --recording excited

# Kitchen environment
python launch_kitchen.py --mode sim-only
python launch_kitchen.py --mode mirror --port /dev/ttyACM0
```

## Modes

| Mode | Hardware | Description |
|------|----------|-------------|
| `sim-only` | None | Play recordings in simulation only |
| `mirror` | /dev/ttyACM0 | Real robot leads, sim follows in real-time |
| `record-sim` | /dev/ttyACM0 | Play recording on both real robot + sim simultaneously |

## Robot Configuration

### Joint Mapping

| Runtime Name | Servo ID | URDF Joint | Kinematic Chain |
|-------------|----------|------------|-----------------|
| base_yaw | 1 | joint_1 | lamparm\_\_wrist\_head -> scs215\_v5 |
| base_pitch | 2 | joint_2 | lamparm\_\_base\_elbow -> lamparm\_\_wrist\_head |
| elbow_pitch | 3 | joint_3 | lamparm\_\_base\_elbow -> lamparm\_\_elbow\_wrist |
| wrist_roll | 4 | joint_4 | lamparm\_\_elbow\_wrist -> lamparm\_\_wrist\_head\_2 |
| wrist_pitch | 5 | joint_5 | lamparm\_\_wrist\_head\_2 -> diffuser |

### Articulation Structure

```
World
└── root_joint (fixed) -> lamparm__base_elbow (articulation root)
    ├── joint_2 -> lamparm__wrist_head
    │   └── joint_1 -> scs215_v5 (kinematic, excluded from articulation)
    │       └── imu_site_frame -> imu_site (excluded from articulation)
    └── joint_3 -> lamparm__elbow_wrist
        └── joint_4 -> lamparm__wrist_head_2
            └── joint_5 -> diffuser (lamp head + DiskLight)
```

### Base Fixture

`scs215_v5` (containing `lamp_base` and `lamp_base_cover` meshes) is the physical lamp base:
- Set to **kinematic** (`PhysicsRigidBodyAPI.kinematicEnabled = True`) so it stays fixed
- `joint_1` and `imu_site_frame` are **excluded from the articulation** (`physics:excludeFromArticulation = True`)
- This decouples the base from the articulation tree while keeping joints 2-5 active

### Joint Calibration

Conversion from runtime normalized values `[-100, 100]` to simulation radians:

```
rad = scale * norm_value + offset
```

| Joint | Scale (rad/unit) | Offset (rad) | Source |
|-------|-----------------|--------------|--------|
| joint_1 | 0.020962 | 0.223194 | base_yaw calibration |
| joint_2 | 0.016437 | 0.272282 | base_pitch calibration |
| joint_3 | 0.012885 | -1.285476 | elbow_pitch calibration |
| joint_4 | 0.031408 | -0.000767 | wrist_roll calibration |
| joint_5 | 0.017020 | 1.241757 | wrist_pitch calibration |

Derived from: `~/.cache/huggingface/lerobot/calibration/robots/lelamp_follower/lelamp.json`

Formula:
1. `ticks = ((norm + 100) / 200) * (range_max - range_min) + range_min`
2. `rad = ((ticks - 2048) / 4096) * 2pi`
3. Simplified to: `rad = scale * norm + offset`

### Real Robot Communication

Uses `scservo_sdk` directly (not `lerobot`) to avoid Python version mismatch between Isaac Sim (3.11) and lelamp_runtime venv (3.12).

- **Protocol**: Feetech STS3215 serial protocol
- **Baud rate**: 1 Mbps
- **Read**: `Present_Position` at address 56 (2 bytes), group sync read
- **Write**: `Goal_Position` at address 42 (2 bytes), group sync write with calibrated tick conversion
- **Mirror mode**: Background thread reads servos at 60 FPS, main loop reads latest values non-blocking

### Drive Parameters

Matching real robot PID coefficients:
- **P (stiffness)**: 16 (real robot default reduced from 32 to avoid shakiness)
- **I**: 0
- **D (damping)**: 32

## USD Fixes Applied

1. **Chinese prim names** (`金属舵盘_驱动/从动`) renamed to `metal_horn_drive/driven` in `robot_base.usd` and `robot_physics.usd` (run `fix_usd.py`)
2. **Broken imu_site reference** cleared in `robot_base.usd`
3. **Black material** applied to all 63 visual meshes
4. **DiskLight** added to `/simulation/diffuser/lamp_light` (warm white, 90 deg cone)

## URDF Fixes Applied

1. **Chinese material names** renamed to ASCII (mesh filenames kept as-is for STL references)
2. **Numeric joint names** (`1`-`5`) renamed to `joint_1`-`joint_5`
3. Original backed up as `robot.urdf.bak`

## Recordings

Located at `/home/zeux/lelamp_runtime/lelamp/recordings/`:

| Name | Description |
|------|-------------|
| curious | Curious looking around |
| excited | Excited bouncing |
| happy_wiggle | Happy side-to-side wiggle |
| headshake | Shaking head no |
| idle | Idle breathing motion |
| nod | Nodding yes |
| sad | Drooping sad pose |
| scanning | Scanning environment |
| shock | Surprised reaction |
| shy | Shy retreating motion |
| wake_up | Waking up animation |

Format: CSV with columns `timestamp, base_yaw.pos, base_pitch.pos, elbow_pitch.pos, wrist_roll.pos, wrist_pitch.pos` at 30 FPS.

## Dependencies

- **Isaac Sim** (pip install `isaacsim` in conda env `leisaac`)
- **scservo_sdk** (for real robot communication)
- **Python 3.11** (Isaac Sim requirement)

## Troubleshooting

### Sim app shuts down immediately
Use `while True: simulation_app.update()` loop pattern. Do NOT use `World.step()` or `simulation_app.is_running()` — they cause premature shutdown with pip-installed Isaac Sim.

### "Physics Simulation View not created" warning
Add warm-up steps after `articulation.initialize()`:
```python
for _ in range(20):
    simulation_app.update()
```

### Joint motions don't match real robot
Check calibration file matches: `~/.cache/huggingface/lerobot/calibration/robots/lelamp_follower/lelamp.json`. Re-run `uv run -m lelamp.calibrate` if needed.

### "ModuleNotFoundError: lerobot"
Expected — the scripts use `scservo_sdk` directly instead of `lerobot` to avoid the Python 3.11/3.12 version mismatch.
