"""
LeLamp Isaac Sim launcher — digital twin with real robot mirroring.

Modes:
    sim-only    : Load robot in Isaac Sim, play recordings in simulation
    mirror      : Read real robot joint positions from /dev/ttyACM0 and mirror in sim
    record-sim  : Play a recording in both sim and real robot simultaneously

Usage:
    python launch_isaacsim.py --mode sim-only --recording curious
    python launch_isaacsim.py --mode mirror --port /dev/ttyACM0
    python launch_isaacsim.py --mode record-sim --port /dev/ttyACM0 --recording excited
"""

import argparse
import csv
import math
import os
import sys
import threading
import time

# --- Isaac Sim must init first ---
from isaacsim import SimulationApp

simulation_app = SimulationApp({"headless": False})

# --- All omni/pxr imports AFTER SimulationApp ---
import numpy as np
import omni.usd
import omni.timeline

try:
    from isaacsim.core.utils.stage import add_reference_to_stage
    from isaacsim.core.prims import SingleArticulation as Articulation
except ImportError:
    from omni.isaac.core.utils.stage import add_reference_to_stage
    from omni.isaac.core.articulations import Articulation

from pxr import Gf, UsdLux, UsdGeom, UsdPhysics

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROBOT_USD = os.path.join(SCRIPT_DIR, "robot", "robot.usd")
ROBOT_PRIM_PATH = "/World/LeLamp"
RECORDINGS_DIR = os.path.join(
    os.path.dirname(SCRIPT_DIR), "lelamp_runtime", "lelamp", "recordings"
)
if not os.path.isdir(RECORDINGS_DIR):
    RECORDINGS_DIR = "/home/zeux/lelamp_runtime/lelamp/recordings"

# ---------------------------------------------------------------------------
# Joint mapping: runtime CSV column → URDF joint name
# ---------------------------------------------------------------------------
JOINT_MAP = {
    "base_yaw.pos":    "joint_1",
    "base_pitch.pos":  "joint_2",
    "elbow_pitch.pos": "joint_3",
    "wrist_roll.pos":  "joint_4",
    "wrist_pitch.pos": "joint_5",
}

# Per-joint conversion from normalized [-100, 100] to radians.
# Calibration: ~/.cache/huggingface/lerobot/calibration/robots/lelamp_follower/lelamp.json
# USD joints have symmetric limits centered at 0, matching the calibration center.
# Formula: rad = scale * norm_value  (no offset — both centered at zero)
JOINT_CONVERSION = {
    "joint_1": {"scale": 0.020962, "offset": 0.223194},   # base_yaw
    "joint_2": {"scale": 0.016437, "offset": 0.272282},   # base_pitch
    "joint_3": {"scale": 0.012885, "offset": -1.285476},  # elbow_pitch
    "joint_4": {"scale": 0.031408, "offset": -0.000767},  # wrist_roll
    "joint_5": {"scale": 0.017020, "offset": 1.241757},   # wrist_pitch
}


# ---------------------------------------------------------------------------
# Scene setup
# ---------------------------------------------------------------------------
def setup_scene(stage):
    """Physics scene + ground + lighting."""
    # Physics scene
    UsdPhysics.Scene.Define(stage, "/World/PhysicsScene")
    ps = UsdPhysics.Scene.Get(stage, "/World/PhysicsScene")
    ps.GetGravityDirectionAttr().Set(Gf.Vec3f(0, 0, -1))
    ps.GetGravityMagnitudeAttr().Set(9.81)

    # Flat grid ground (Isaac Sim style)
    from pxr import UsdShade, Sdf

    SIZE = 20.0
    CELLS = 40
    cell = SIZE / CELLS
    h = SIZE / 2

    # Ground collision plane
    ground = UsdGeom.Mesh.Define(stage, "/World/FlatGrid/Ground")
    ground.GetPointsAttr().Set([(-h, -h, 0), (h, -h, 0), (h, h, 0), (-h, h, 0)])
    ground.GetFaceVertexCountsAttr().Set([4])
    ground.GetFaceVertexIndicesAttr().Set([0, 1, 2, 3])
    ground.GetNormalsAttr().Set([(0, 0, 1)] * 4)
    ground.GetDoubleSidedAttr().Set(True)
    UsdPhysics.CollisionAPI.Apply(ground.GetPrim())

    # Ground material — dark
    gm = UsdShade.Material.Define(stage, "/World/FlatGrid/GroundMat")
    gs = UsdShade.Shader.Define(stage, "/World/FlatGrid/GroundMat/Shader")
    gs.CreateIdAttr("UsdPreviewSurface")
    gs.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(0.08, 0.08, 0.08))
    gs.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.9)
    gm.CreateSurfaceOutput().ConnectToSource(gs.ConnectableAPI(), "surface")
    UsdShade.MaterialBindingAPI(ground.GetPrim()).Bind(gm)

    # Grid lines — thin bright lines
    pts = []
    cnts = []
    for i in range(CELLS + 1):
        p = -h + i * cell
        pts += [(p, -h, 0.0005), (p, h, 0.0005)]
        cnts.append(2)
        pts += [(-h, p, 0.0005), (h, p, 0.0005)]
        cnts.append(2)

    lines = UsdGeom.BasisCurves.Define(stage, "/World/FlatGrid/GridLines")
    lines.GetPointsAttr().Set(pts)
    lines.GetCurveVertexCountsAttr().Set(cnts)
    lines.GetTypeAttr().Set("linear")
    lines.GetWidthsAttr().Set([0.003] * len(pts))

    lm = UsdShade.Material.Define(stage, "/World/FlatGrid/LineMat")
    ls = UsdShade.Shader.Define(stage, "/World/FlatGrid/LineMat/Shader")
    ls.CreateIdAttr("UsdPreviewSurface")
    ls.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(0.25, 0.25, 0.25))
    ls.CreateInput("emissiveColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(0.15, 0.15, 0.15))
    lm.CreateSurfaceOutput().ConnectToSource(ls.ConnectableAPI(), "surface")
    UsdShade.MaterialBindingAPI(lines.GetPrim()).Bind(lm)

    # Lighting
    dome = UsdLux.DomeLight.Define(stage, "/World/DomeLight")
    dome.GetIntensityAttr().Set(500.0)
    dome.GetColorAttr().Set(Gf.Vec3f(0.85, 0.9, 1.0))

    distant = UsdLux.DistantLight.Define(stage, "/World/DistantLight")
    distant.GetIntensityAttr().Set(3000.0)
    distant.GetAngleAttr().Set(0.53)
    xf2 = UsdGeom.Xformable(distant.GetPrim())
    xf2.AddRotateXYZOp().Set(Gf.Vec3d(-45.0, 30.0, 0.0))


def load_robot(stage):
    if not os.path.exists(ROBOT_USD):
        print(f"ERROR: Robot USD not found at {ROBOT_USD}")
        sys.exit(1)
    prim = add_reference_to_stage(usd_path=ROBOT_USD, prim_path=ROBOT_PRIM_PATH)
    # Place robot on the ground — scs215_v5 base bottom is at z≈0 in robot frame
    xf = UsdGeom.Xformable(prim)
    xf.ClearXformOpOrder()
    xf.AddTranslateOp().Set(Gf.Vec3d(0.0, 0.0, 0.0))
    print(f"Loaded robot at {ROBOT_PRIM_PATH}")
    return prim


# ---------------------------------------------------------------------------
# Recordings
# ---------------------------------------------------------------------------
def load_recording(name: str) -> list[dict]:
    csv_path = os.path.join(RECORDINGS_DIR, f"{name}.csv")
    if not os.path.exists(csv_path):
        available = [f[:-4] for f in os.listdir(RECORDINGS_DIR) if f.endswith(".csv")]
        print(f"ERROR: Recording '{name}' not found. Available: {', '.join(sorted(available))}")
        sys.exit(1)
    with open(csv_path) as f:
        rows = list(csv.DictReader(f))
    print(f"Loaded recording '{name}': {len(rows)} frames")
    return rows


def recording_to_joint_targets(row: dict) -> dict[str, float]:
    targets = {}
    for csv_col, urdf_joint in JOINT_MAP.items():
        if csv_col in row:
            norm_val = float(row[csv_col])
            conv = JOINT_CONVERSION[urdf_joint]
            targets[urdf_joint] = conv["scale"] * norm_val + conv["offset"]
    return targets


def list_recordings():
    if not os.path.isdir(RECORDINGS_DIR):
        return []
    return sorted(f[:-4] for f in os.listdir(RECORDINGS_DIR) if f.endswith(".csv"))


# ---------------------------------------------------------------------------
# Real robot (scservo_sdk direct — no lerobot dependency)
# ---------------------------------------------------------------------------
STS3215_PRESENT_POS_ADDR = 56
STS3215_PRESENT_POS_LEN = 2
STS3215_RESOLUTION = 4096
STS3215_BAUDRATE = 1_000_000

SERVO_JOINTS = {
    1: "joint_1",
    2: "joint_2",
    3: "joint_3",
    4: "joint_4",
    5: "joint_5",
}


class FeetechDirectReader:
    def __init__(self, port: str):
        import scservo_sdk as scs
        self._scs = scs
        self.port_handler = scs.PortHandler(port)
        self.packet_handler = scs.PacketHandler(0)

        if not self.port_handler.openPort():
            raise RuntimeError(f"Failed to open {port}")
        if not self.port_handler.setBaudRate(STS3215_BAUDRATE):
            raise RuntimeError(f"Failed to set baud rate on {port}")

        self.sync_read = scs.GroupSyncRead(
            self.port_handler, self.packet_handler,
            STS3215_PRESENT_POS_ADDR, STS3215_PRESENT_POS_LEN,
        )
        for servo_id in SERVO_JOINTS:
            self.sync_read.addParam(servo_id)

        print(f"Connected to servos on {port}")

    def read_positions(self) -> dict[str, float]:
        result = self.sync_read.txRxPacket()
        if result != self._scs.COMM_SUCCESS:
            return {}
        targets = {}
        for servo_id, joint_name in SERVO_JOINTS.items():
            if not self.sync_read.isAvailable(servo_id, STS3215_PRESENT_POS_ADDR, STS3215_PRESENT_POS_LEN):
                continue
            raw = self.sync_read.getData(servo_id, STS3215_PRESENT_POS_ADDR, STS3215_PRESENT_POS_LEN)
            if raw & 0x8000:
                raw = -(raw & 0x7FFF)
            # Convert raw ticks to radians (centered at midpoint 2048)
            # Convert raw ticks to radians (centered at midpoint 2048)
            targets[joint_name] = ((raw - 2048) / STS3215_RESOLUTION) * 2.0 * math.pi
        return targets

    def write_positions(self, csv_row: dict):
        """Write goal positions from CSV row. Uses calibration to convert [-100,100] → ticks."""
        import scservo_sdk as scs

        # Calibration: normalized → ticks = ((norm+100)/200) * (max-min) + min
        CALIBRATION = {
            "base_yaw.pos":    (1, 827, 3560),   # (servo_id, range_min, range_max)
            "base_pitch.pos":  (2, 1154, 3297),
            "elbow_pitch.pos": (3, 370, 2050),
            "wrist_roll.pos":  (4, 0, 4095),
            "wrist_pitch.pos": (5, 1748, 3967),
        }

        sync_write = scs.GroupSyncWrite(
            self.port_handler, self.packet_handler, 42, 2,
        )
        for col, (sid, rmin, rmax) in CALIBRATION.items():
            if col not in csv_row:
                continue
            norm = max(-100.0, min(100.0, float(csv_row[col])))
            raw = int(((norm + 100) / 200.0) * (rmax - rmin) + rmin)
            raw = max(0, min(4095, raw))
            sync_write.addParam(sid, [scs.SCS_LOBYTE(raw), scs.SCS_HIBYTE(raw)])
        sync_write.txPacket()
        sync_write.clearParam()

    def disconnect(self):
        self.port_handler.closePort()


class MirrorReader:
    """Background thread for non-blocking serial reads."""

    def __init__(self, robot, fps=60):
        self._robot = robot
        self._lock = threading.Lock()
        self._latest = {}
        self._running = False
        self._dt = 1.0 / fps

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            t0 = time.perf_counter()
            try:
                pos = self._robot.read_positions()
                with self._lock:
                    self._latest = pos
            except Exception:
                pass
            dt = time.perf_counter() - t0
            if dt < self._dt:
                time.sleep(self._dt - dt)

    def get_latest(self):
        with self._lock:
            return dict(self._latest)


# ---------------------------------------------------------------------------
# Apply joint targets
# ---------------------------------------------------------------------------
def apply_joint_targets(articulation, targets):
    joint_names = articulation.dof_names
    if not joint_names:
        return
    positions = np.zeros(len(joint_names))
    for i, name in enumerate(joint_names):
        if name in targets:
            positions[i] = targets[name]
    # SingleArticulation uses set_joint_positions; legacy uses set_joint_position_targets
    if hasattr(articulation, 'set_joint_position_targets'):
        articulation.set_joint_position_targets(positions)
    else:
        articulation.set_joint_positions(positions)


# ---------------------------------------------------------------------------
# Main — follows the exact pattern proven in test_loop2.py
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="LeLamp Isaac Sim Launcher")
    parser.add_argument("--mode", choices=["sim-only", "mirror", "record-sim"],
                        default="sim-only")
    parser.add_argument("--port", default="/dev/ttyACM0")
    parser.add_argument("--recording", default=None)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--loop", action="store_true")
    args = parser.parse_args()

    if args.mode in ("sim-only", "record-sim") and args.recording is None:
        print(f"Available recordings: {', '.join(list_recordings())}")
        args.recording = input("Enter recording name: ").strip()

    # --- Stage setup (same order as working test_loop2.py) ---
    stage = omni.usd.get_context().get_stage()
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)

    setup_scene(stage)
    load_robot(stage)

    # Warm up
    for _ in range(5):
        simulation_app.update()

    # Timeline
    timeline = omni.timeline.get_timeline_interface()
    timeline.play()

    for _ in range(5):
        simulation_app.update()

    # Articulation — needs physics to be fully stepped before the view works
    try:
        articulation = Articulation(prim_path=ROBOT_PRIM_PATH)
        articulation.initialize()

        # Step physics so the simulation view gets created
        for _ in range(20):
            simulation_app.update()

        print(f"Articulation OK: {articulation.dof_names}")
    except Exception as e:
        print(f"Articulation failed: {e} — running without joint control")
        articulation = None

    print("=" * 55)
    print(f"LeLamp Isaac Sim  |  mode: {args.mode}")
    print("=" * 55)

    # --- Real robot ---
    real_robot = None
    mirror_reader = None
    if args.mode in ("mirror", "record-sim"):
        real_robot = FeetechDirectReader(args.port)

    if args.mode == "mirror" and real_robot:
        mirror_reader = MirrorReader(real_robot, fps=60)
        mirror_reader.start()

    # --- Interactive recording selector ---
    recordings = list_recordings()
    frames = None
    frame_idx = 0
    frame_dt = 1.0 / args.fps
    playing = False
    current_name = ""

    def show_menu():
        print("\n" + "=" * 55)
        print("Available recordings:")
        for i, name in enumerate(recordings, 1):
            print(f"  {i:2d}. {name}")
        print(f"   q. Quit")
        print("=" * 55)

    def prompt_recording():
        nonlocal frames, frame_idx, playing, current_name
        show_menu()
        while True:
            choice = input("Choose recording (number or name): ").strip()
            if choice.lower() == 'q':
                return False
            # Try as number
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(recordings):
                    current_name = recordings[idx]
                    frames = load_recording(current_name)
                    frame_idx = 0
                    playing = True
                    return True
            except ValueError:
                pass
            # Try as name
            if choice in recordings:
                current_name = choice
                frames = load_recording(current_name)
                frame_idx = 0
                playing = True
                return True
            print(f"Invalid choice: '{choice}'")

    # Load initial recording if provided via args
    if args.mode in ("sim-only", "record-sim") and args.recording:
        frames = load_recording(args.recording)
        current_name = args.recording
        frame_idx = 0
        playing = True
    elif args.mode in ("sim-only", "record-sim"):
        if not prompt_recording():
            simulation_app.close()
            return

    print(f"Running... (Ctrl+C to stop)")

    try:
        while True:
            t0 = time.perf_counter()

            if args.mode == "mirror" and mirror_reader and articulation:
                targets = mirror_reader.get_latest()
                if targets:
                    apply_joint_targets(articulation, targets)

            elif args.mode in ("sim-only", "record-sim") and playing and frames and articulation:
                if frame_idx < len(frames):
                    row = frames[frame_idx]
                    targets = recording_to_joint_targets(row)
                    apply_joint_targets(articulation, targets)

                    if args.mode == "record-sim" and real_robot:
                        real_robot.write_positions(row)

                    frame_idx += 1
                else:
                    # Recording finished — prompt for next
                    playing = False
                    print(f"\n'{current_name}' done.")
                    if not prompt_recording():
                        break

            simulation_app.update()

            elapsed = time.perf_counter() - t0
            if elapsed < frame_dt:
                time.sleep(frame_dt - elapsed)

    except (KeyboardInterrupt, SystemExit):
        pass

    # --- Cleanup ---
    print("Shutting down...")
    timeline.stop()
    if mirror_reader:
        mirror_reader.stop()
    if real_robot:
        real_robot.disconnect()
    simulation_app.close()


if __name__ == "__main__":
    main()
