"""
LeLamp in Kitchen — Isaac Sim scene with kitchen environment and robot.

Usage:
    python launch_kitchen.py --mode sim-only
    python launch_kitchen.py --mode record-sim --port /dev/ttyACM0
    python launch_kitchen.py --mode mirror --port /dev/ttyACM0
"""

import argparse
import csv
import math
import os
import sys
import threading
import time

from isaacsim import SimulationApp

simulation_app = SimulationApp({"headless": False})

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
KITCHEN_USD = "/home/zeux/Downloads/kitchen_with_orange/scene.usd"
ROBOT_PRIM_PATH = "/World/LeLamp"

RECORDINGS_DIR = os.path.join(
    os.path.dirname(SCRIPT_DIR), "lelamp_runtime", "lelamp", "recordings"
)
if not os.path.isdir(RECORDINGS_DIR):
    RECORDINGS_DIR = "/home/zeux/lelamp_runtime/lelamp/recordings"

# ---------------------------------------------------------------------------
# Joint mapping
# ---------------------------------------------------------------------------
JOINT_MAP = {
    "base_yaw.pos":    "joint_1",
    "base_pitch.pos":  "joint_2",
    "elbow_pitch.pos": "joint_3",
    "wrist_roll.pos":  "joint_4",
    "wrist_pitch.pos": "joint_5",
}

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
    """Load kitchen environment and place robot."""
    # Physics scene (skip if kitchen already has one)
    if not stage.GetPrimAtPath("/World/PhysicsScene").IsValid():
        UsdPhysics.Scene.Define(stage, "/World/PhysicsScene")
        ps = UsdPhysics.Scene.Get(stage, "/World/PhysicsScene")
        ps.GetGravityDirectionAttr().Set(Gf.Vec3f(0, 0, -1))
        ps.GetGravityMagnitudeAttr().Set(9.81)

    # Load kitchen environment
    if os.path.exists(KITCHEN_USD):
        add_reference_to_stage(usd_path=KITCHEN_USD, prim_path="/World/Kitchen")
        print(f"Loaded kitchen: {KITCHEN_USD}")
    else:
        print(f"WARNING: Kitchen USD not found at {KITCHEN_USD}")

    # Load robot at the specified position/orientation on the kitchen counter
    if not os.path.exists(ROBOT_USD):
        print(f"ERROR: Robot USD not found at {ROBOT_USD}")
        sys.exit(1)

    prim = add_reference_to_stage(usd_path=ROBOT_USD, prim_path=ROBOT_PRIM_PATH)
    xf = UsdGeom.Xformable(prim)
    xf.ClearXformOpOrder()
    P = UsdGeom.XformOp.PrecisionDouble
    xf.AddTranslateOp(precision=P).Set(Gf.Vec3d(1.878, -0.430, 0.922))
    # Orientation: euler X=-6.666° Y=0 Z=0
    import math
    rx = math.radians(-6.666)
    xf.AddOrientOp(precision=P).Set(Gf.Quatd(math.cos(rx/2), math.sin(rx/2), 0, 0))
    xf.AddScaleOp(precision=P).Set(Gf.Vec3d(1, 1, 1))
    print(f"Loaded robot at {ROBOT_PRIM_PATH} (on kitchen counter)")

    # Extra lighting to complement kitchen
    dome = UsdLux.DomeLight.Define(stage, "/World/DomeLight")
    dome.GetIntensityAttr().Set(300.0)
    dome.GetColorAttr().Set(Gf.Vec3f(1.0, 0.95, 0.9))


# ---------------------------------------------------------------------------
# Recordings
# ---------------------------------------------------------------------------
def load_recording(name):
    csv_path = os.path.join(RECORDINGS_DIR, f"{name}.csv")
    if not os.path.exists(csv_path):
        available = sorted(f[:-4] for f in os.listdir(RECORDINGS_DIR) if f.endswith(".csv"))
        print(f"ERROR: '{name}' not found. Available: {', '.join(available)}")
        sys.exit(1)
    with open(csv_path) as f:
        rows = list(csv.DictReader(f))
    print(f"Loaded '{name}': {len(rows)} frames")
    return rows


def recording_to_joint_targets(row):
    targets = {}
    for csv_col, urdf_joint in JOINT_MAP.items():
        if csv_col in row:
            conv = JOINT_CONVERSION[urdf_joint]
            targets[urdf_joint] = conv["scale"] * float(row[csv_col]) + conv["offset"]
    return targets


def list_recordings():
    if not os.path.isdir(RECORDINGS_DIR):
        return []
    return sorted(f[:-4] for f in os.listdir(RECORDINGS_DIR) if f.endswith(".csv"))


# ---------------------------------------------------------------------------
# Real robot (scservo_sdk)
# ---------------------------------------------------------------------------
STS3215_RESOLUTION = 4096


class FeetechDirectReader:
    def __init__(self, port):
        import scservo_sdk as scs
        self._scs = scs
        self.port_handler = scs.PortHandler(port)
        self.packet_handler = scs.PacketHandler(0)
        if not self.port_handler.openPort():
            raise RuntimeError(f"Failed to open {port}")
        if not self.port_handler.setBaudRate(1_000_000):
            raise RuntimeError(f"Failed to set baud rate")
        self.sync_read = scs.GroupSyncRead(self.port_handler, self.packet_handler, 56, 2)
        for sid in range(1, 6):
            self.sync_read.addParam(sid)
        print(f"Connected to servos on {port}")

    SERVO_JOINTS = {1: "joint_1", 2: "joint_2", 3: "joint_3", 4: "joint_4", 5: "joint_5"}

    def read_positions(self):
        result = self.sync_read.txRxPacket()
        if result != self._scs.COMM_SUCCESS:
            return {}
        targets = {}
        for sid, jname in self.SERVO_JOINTS.items():
            if not self.sync_read.isAvailable(sid, 56, 2):
                continue
            raw = self.sync_read.getData(sid, 56, 2)
            if raw & 0x8000:
                raw = -(raw & 0x7FFF)
            targets[jname] = ((raw - 2048) / STS3215_RESOLUTION) * 2.0 * math.pi
        return targets

    def write_positions(self, csv_row):
        import scservo_sdk as scs
        CALIBRATION = {
            "base_yaw.pos": (1, 827, 3560), "base_pitch.pos": (2, 1154, 3297),
            "elbow_pitch.pos": (3, 370, 2050), "wrist_roll.pos": (4, 0, 4095),
            "wrist_pitch.pos": (5, 1748, 3967),
        }
        sw = scs.GroupSyncWrite(self.port_handler, self.packet_handler, 42, 2)
        for col, (sid, rmin, rmax) in CALIBRATION.items():
            if col not in csv_row:
                continue
            norm = max(-100.0, min(100.0, float(csv_row[col])))
            raw = int(((norm + 100) / 200.0) * (rmax - rmin) + rmin)
            raw = max(0, min(4095, raw))
            sw.addParam(sid, [scs.SCS_LOBYTE(raw), scs.SCS_HIBYTE(raw)])
        sw.txPacket()
        sw.clearParam()

    def disconnect(self):
        self.port_handler.closePort()


class MirrorReader:
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
    if hasattr(articulation, 'set_joint_position_targets'):
        articulation.set_joint_position_targets(positions)
    else:
        articulation.set_joint_positions(positions)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="LeLamp Kitchen Scene")
    parser.add_argument("--mode", choices=["sim-only", "mirror", "record-sim"], default="sim-only")
    parser.add_argument("--port", default="/dev/ttyACM0")
    parser.add_argument("--recording", default=None)
    parser.add_argument("--fps", type=int, default=30)
    args = parser.parse_args()

    # --- Stage setup ---
    stage = omni.usd.get_context().get_stage()
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)

    setup_scene(stage)

    # Warm up
    for _ in range(5):
        simulation_app.update()

    # Timeline
    timeline = omni.timeline.get_timeline_interface()
    timeline.play()
    for _ in range(5):
        simulation_app.update()

    # Articulation
    try:
        articulation = Articulation(prim_path=ROBOT_PRIM_PATH)
        articulation.initialize()
        for _ in range(20):
            simulation_app.update()
        print(f"Articulation OK: {articulation.dof_names}")
    except Exception as e:
        print(f"Articulation failed: {e}")
        articulation = None

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
            if choice in recordings:
                current_name = choice
                frames = load_recording(current_name)
                frame_idx = 0
                playing = True
                return True
            print(f"Invalid: '{choice}'")

    # Initial recording
    if args.mode in ("sim-only", "record-sim"):
        if args.recording:
            frames = load_recording(args.recording)
            current_name = args.recording
            playing = True
        else:
            if not prompt_recording():
                simulation_app.close()
                return

    print(f"\n{'='*55}")
    print(f"LeLamp Kitchen  |  mode: {args.mode}")
    print(f"{'='*55}")
    print("Running... (Ctrl+C to stop)")

    # --- Main loop ---
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

    print("Shutting down...")
    timeline.stop()
    if mirror_reader:
        mirror_reader.stop()
    if real_robot:
        real_robot.disconnect()
    simulation_app.close()


if __name__ == "__main__":
    main()
