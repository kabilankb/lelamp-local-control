# Building a Digital Twin for an Open-Source Robot Lamp in NVIDIA Isaac Sim

*How we brought LeLamp — a 5-axis expressive robot lamp — into simulation with real-time hardware mirroring*

---

The LeLamp project by Human Computer Lab is an open-source robot lamp inspired by Apple's ELEGNT research. It features 5 servo-driven joints, a camera, LEDs, and a personality powered by AI. We built a physical one — and then we wanted a digital twin.

This post walks through how we set up LeLamp in NVIDIA Isaac Sim, solved the real challenges of URDF-to-USD conversion, and connected the simulation to real hardware for synchronized control.

## Why a Digital Twin?

Building a robot lamp is fun. Breaking one while testing new movements is not.

A digital twin lets you:

- **Test animations safely** before running them on hardware
- **Mirror the real robot** in simulation for visualization and debugging
- **Develop new behaviors** without physical access to the robot
- **Run multiple experiments** simultaneously across different environments

Isaac Sim was our choice because of its PhysX-based articulation support and USD scene composition, which maps well to our URDF-based robot description.

## The Robot

LeLamp has 5 joints driven by Feetech STS3215 servos:

| Joint | Function | Range |
|-------|----------|-------|
| base_yaw | Base rotation | ~240 degrees |
| base_pitch | Base tilt | ~188 degrees |
| elbow_pitch | Middle joint bend | ~148 degrees |
| wrist_roll | Lamp head rotation | ~360 degrees |
| wrist_pitch | Lamp head tilt | ~195 degrees |

The control software runs on a Raspberry Pi and uses the `lerobot` framework from Hugging Face for servo communication. Movements are stored as CSV recordings at 30 FPS — each row contains normalized joint positions in the range [-100, 100].

## Step 1: URDF to USD

LeLamp's URDF was generated from its Onshape CAD model using `onshape-to-robot`. The first obstacle: the URDF contained Chinese characters in part names (from the original CAD) and numeric-only joint names.

```xml
<!-- Original URDF problems -->
<material name="金属舵盘_驱动__v2_material">  <!-- Not valid USD -->
<joint name="1" type="revolute">              <!-- Not valid USD -->
```

Isaac Sim's URDF importer silently mangled these into `a_____________________v2_material` and `a_`, losing the original meaning. We fixed the URDF before import:

- Chinese material names became `metal_horn_drive_v2`, `metal_horn_driven_v2`
- Numeric joints became `joint_1` through `joint_5`
- Mesh filenames were kept unchanged (they reference actual STL files on disk)

After importing into Isaac Sim, we also had to fix the generated USD files — 240 Chinese-character prims in the visual and collider hierarchies needed renaming, and a broken IMU sensor reference needed clearing.

## Step 2: The Base Fixture Problem

This was the trickiest part. In the real robot, `scs215_v5` (the servo housing at the bottom) is bolted to a table — it never moves. But in the URDF tree, it's a *leaf node*, not the root.

The URDF tree looks like this:

```
lamparm__base_elbow (URDF root)
├── joint_2 → lamparm__wrist_head
│   └── joint_1 → scs215_v5        ← should be fixed!
└── joint_3 → lamparm__elbow_wrist
    └── joint_4 → lamparm__wrist_head_2
        └── joint_5 → diffuser     ← lamp head
```

We tried several approaches:

**Attempt 1: Reverse the joint chain** — Swap body0/body1 on joint_1 and joint_2, make scs215_v5 the articulation root. This broke the articulation dynamics and required negating joint angle signs, creating a cascade of issues.

**Attempt 2: Set fixBase on the articulation root** — Didn't work because the articulation root was still `lamparm__base_elbow`, not `scs215_v5`.

**What actually worked — three targeted changes:**

1. Made `scs215_v5` **kinematic** — physics forces don't affect it
2. Set `joint_1` to **excludeFromArticulation** — decouples the base from the articulation solver
3. Set `imu_site_frame` to **excludeFromArticulation** — its parent is now outside the articulation

```python
# The fix in robot_physics.usd
scs215_v5:     kinematicEnabled = True
joint_1:       excludeFromArticulation = True
imu_site_frame: excludeFromArticulation = True
```

The articulation root (`lamparm__base_elbow`) stays fixed to the world via `root_joint`, and joints 2-5 drive the arm normally. The base mesh stays put.

## Step 3: Joint Calibration Mapping

The real robot's servo positions are normalized to [-100, 100] using calibration data. Each servo has a different physical range (min/max ticks out of 4096). To drive the simulation correctly, we needed per-joint conversion:

```python
# rad = scale * normalized_value + offset
JOINT_CONVERSION = {
    "joint_1": {"scale": 0.020962, "offset": 0.223194},   # base_yaw
    "joint_2": {"scale": 0.016437, "offset": 0.272282},   # base_pitch
    "joint_3": {"scale": 0.012885, "offset": -1.285476},  # elbow_pitch
    "joint_4": {"scale": 0.031408, "offset": -0.000767},  # wrist_roll
    "joint_5": {"scale": 0.017020, "offset": 1.241757},   # wrist_pitch
}
```

The offsets aren't zero because the calibration ranges aren't centered at the servo's midpoint (tick 2048). We derived these from the calibration file that `lerobot` generates during the robot's initial setup.

## Step 4: Real Robot Communication

LeLamp's runtime uses `lerobot` (Python 3.12), but Isaac Sim ships with Python 3.11. Instead of fighting version mismatches, we wrote a lightweight `FeetechDirectReader` class that talks to the servos using `scservo_sdk` directly:

```python
class FeetechDirectReader:
    def read_positions(self):
        """Group sync read of all 5 servos at 1 Mbps."""
        # Read Present_Position (address 56, 2 bytes)
        # Convert raw ticks to radians
        
    def write_positions(self, csv_row):
        """Write goal positions using calibrated tick conversion."""
        # Convert normalized [-100,100] back to ticks using calibration
        # Group sync write to Goal_Position (address 42)
```

For the mirror mode, a background thread reads servo positions at 60 FPS and stores the latest values. The simulation loop reads them non-blocking, keeping the render smooth even if a serial read stalls.

## Step 5: The Isaac Sim Loop

One non-obvious lesson: with pip-installed Isaac Sim, the standard patterns from the documentation don't work:

```python
# This exits immediately:
while simulation_app.is_running():
    world.step(render=True)

# This also exits after 1-2 frames:
while simulation_app.is_running():
    simulation_app.update()
```

What works:

```python
# The pattern that actually keeps the window open:
timeline.play()
for _ in range(5):
    simulation_app.update()  # warm up

while True:
    # ... update joint targets ...
    simulation_app.update()
```

No `World` class, no `is_running()` check — just `timeline.play()` and a `while True` loop with `simulation_app.update()`. We discovered this through systematic elimination using minimal test scripts.

## The Result

Three operational modes from a single script:

```bash
# Play animations in simulation
python launch_isaacsim.py --mode sim-only --recording happy_wiggle --loop

# Real robot mirrors to simulation in real-time
python launch_isaacsim.py --mode mirror --port /dev/ttyACM0

# Synchronized playback on both
python launch_isaacsim.py --mode record-sim --port /dev/ttyACM0
```

An interactive menu lets you pick from 12 pre-recorded animations (curious, excited, happy_wiggle, nod, sad, etc.) and play them one after another. A separate kitchen environment script places the lamp on a counter for more realistic scenarios.

## Lessons Learned

1. **Don't reverse joint body0/body1** to fix a base link. Use `kinematicEnabled` + `excludeFromArticulation` instead.

2. **USD layer composition matters.** Changes in `robot_physics.usd` can be overridden by `robot_base.usd` depending on sublayer order. Check the composed stage, not individual files.

3. **Calibration offsets are real.** A generic "300 degrees / 200 units" conversion doesn't work when each servo has a different calibrated range with an asymmetric center.

4. **Isaac Sim's pip install behaves differently** from the Omniverse Launcher version. Test with minimal scripts before building complex setups.

5. **scservo_sdk is your friend.** When framework dependencies conflict, going one level lower to the servo protocol library solves the problem cleanly.

## Links

- LeLamp project: [github.com/humancomputerlab/LeLamp](https://github.com/humancomputerlab/LeLamp)
- Simulation code: [github.com/kabilankb/lelamp-local-control](https://github.com/kabilankb/lelamp-local-control/tree/feature/isaacsim-digital-twin)
- LeLamp runtime: [github.com/humancomputerlab/lelamp_runtime](https://github.com/humancomputerlab/lelamp_runtime)
- Human Computer Lab: [humancomputerlab.com](https://www.humancomputerlab.com/)
- Apple ELEGNT: [machinelearning.apple.com/research/elegnt-expressive-functional-movement](https://machinelearning.apple.com/research/elegnt-expressive-functional-movement)

---

*Built by the Human Computer Lab community. Join us on [Discord](https://discord.gg/727JXBt8Zt).*
