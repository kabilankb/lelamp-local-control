"""
Add a Disk Light to the diffuser link of the LeLamp robot USD.

Usage in Isaac Sim Script Editor or standalone:
    python add_diffuser_light.py

This attaches a downward-facing disk light as a child of the diffuser prim,
so it moves with the lamp head during simulation.
"""

from pxr import Usd, UsdLux, UsdGeom, Gf

USD_PATH = "robot/robot.usd"
DIFFUSER_PRIM_PATH = "/simulation/diffuser"
LIGHT_PRIM_PATH = "/simulation/diffuser/lamp_light"

# Light parameters - adjust these to match your real lamp
LIGHT_INTENSITY = 5000.0       # Luminous power (candela-ish in Isaac Sim)
LIGHT_COLOR = Gf.Vec3f(1.0, 0.95, 0.85)  # Warm white
LIGHT_RADIUS = 0.03            # Disk radius in meters (~3cm, matches diffuser)
CONE_ANGLE = 90.0              # Spread angle in degrees
CONE_SOFTNESS = 0.2            # Edge softness


def add_light(usd_path=USD_PATH):
    stage = Usd.Stage.Open(usd_path)

    diffuser = stage.GetPrimAtPath(DIFFUSER_PRIM_PATH)
    if not diffuser.IsValid():
        print(f"ERROR: {DIFFUSER_PRIM_PATH} not found in {usd_path}")
        print("Available top-level prims:")
        for p in stage.GetPseudoRoot().GetChildren():
            print(f"  {p.GetPath()}")
        return False

    # Remove existing light if re-running
    existing = stage.GetPrimAtPath(LIGHT_PRIM_PATH)
    if existing.IsValid():
        stage.RemovePrim(LIGHT_PRIM_PATH)
        print(f"Removed existing light at {LIGHT_PRIM_PATH}")

    # Create a DiskLight as child of diffuser
    light = UsdLux.DiskLight.Define(stage, LIGHT_PRIM_PATH)

    # Position: at the diffuser visual origin, pointing downward (-Z in local frame)
    xform = UsdGeom.Xformable(light.GetPrim())
    xform.ClearXformOpOrder()

    # Translate to match diffuser opening
    xform.AddTranslateOp().Set(Gf.Vec3d(-0.002, 0.002, 0.039))

    # Rotate so light points downward (along -Z of the diffuser frame)
    # The disk light emits along its -Z axis by default
    xform.AddRotateXYZOp().Set(Gf.Vec3d(180.0, 0.0, 0.0))

    # Set light properties
    light.GetIntensityAttr().Set(LIGHT_INTENSITY)
    light.GetColorAttr().Set(LIGHT_COLOR)
    light.GetRadiusAttr().Set(LIGHT_RADIUS)

    # Shaping (cone/spot) - makes it directional like a real desk lamp
    shaping = UsdLux.ShapingAPI.Apply(light.GetPrim())
    shaping.GetShapingConeAngleAttr().Set(CONE_ANGLE)
    shaping.GetShapingConeSoftnessAttr().Set(CONE_SOFTNESS)

    stage.GetRootLayer().Save()
    print(f"Added DiskLight at {LIGHT_PRIM_PATH}")
    print(f"  Intensity: {LIGHT_INTENSITY}")
    print(f"  Color: {LIGHT_COLOR}")
    print(f"  Radius: {LIGHT_RADIUS}m")
    print(f"  Cone angle: {CONE_ANGLE}°")
    return True


if __name__ == "__main__":
    add_light()
