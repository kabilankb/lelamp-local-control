"""
Fix LeLamp robot USD files:
1. Rename Chinese character prims (金属舵盘_驱动/从动) to ASCII
2. Fix broken imu_site visual reference
"""

import os
from pxr import Usd, Sdf

ROBOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "robot")

# Chinese → ASCII prim name mapping
RENAME_MAP = {
    "金属舵盘_驱动__v2": "metal_horn_drive_v2",
    "金属舵盘_从动__v2": "metal_horn_driven_v2",
    "金属舵盘_驱动__v2_2": "metal_horn_drive_v2_2",
    "金属舵盘_从动__v2_2": "metal_horn_driven_v2_2",
    "金属舵盘_驱动__v2_3": "metal_horn_drive_v2_3",
    "金属舵盘_从动__v2_3": "metal_horn_driven_v2_3",
    "金属舵盘_驱动__v2_4": "metal_horn_drive_v2_4",
    "金属舵盘_从动__v2_4": "metal_horn_driven_v2_4",
    "金属舵盘_驱动__v2_5": "metal_horn_drive_v2_5",
    "金属舵盘_从动__v2_5": "metal_horn_driven_v2_5",
}


def rename_chinese_prims(layer):
    """Rename all Chinese-character prims in a USD layer."""
    renamed = 0

    # We need to work on the Sdf layer directly to rename prims
    # Collect all paths that need renaming
    renames = []
    for path in layer.rootPrims:
        _collect_renames(layer, path.path, renames)

    # Apply renames in reverse depth order (deepest first)
    renames.sort(key=lambda x: -x[0].pathElementCount)

    for old_path, new_path in renames:
        if layer.GetPrimAtPath(old_path):
            # Use Sdf.BatchNamespaceEdit for safe renaming
            edit = Sdf.BatchNamespaceEdit()
            edit.Add(old_path, new_path)
            if layer.Apply(edit):
                renamed += 1
            else:
                print(f"  WARN: Failed to rename {old_path} → {new_path}")

    return renamed


def _collect_renames(layer, path, renames):
    """Recursively find prims that need Chinese→ASCII renaming."""
    prim_spec = layer.GetPrimAtPath(path)
    if prim_spec is None:
        return

    name = path.name
    if name in RENAME_MAP:
        parent = path.GetParentPath()
        new_path = parent.AppendChild(RENAME_MAP[name])
        renames.append((path, new_path))

    # Recurse into children
    for child in prim_spec.nameChildren:
        child_path = path.AppendChild(child.name)
        _collect_renames(layer, child_path, renames)


def fix_imu_site_reference(layer_path):
    """Fix the broken imu_site visual reference in robot_base.usd."""
    layer = Sdf.Layer.FindOrOpen(layer_path)
    if layer is None:
        return False

    # The imu_site visual reference points to robot_physics.usd which doesn't
    # have the visual — it's a sensor-only link with no mesh. Remove the reference.
    imu_vis_path = Sdf.Path("/simulation/imu_site/visuals")
    prim_spec = layer.GetPrimAtPath(imu_vis_path)
    if prim_spec is not None:
        refs = prim_spec.referenceList
        # Clear all references on this prim (they point to nonexistent visuals)
        refs.ClearEdits()
        layer.Save()
        print(f"  Fixed imu_site/visuals references in {os.path.basename(layer_path)}")
        return True
    return False


def process_file(filepath):
    """Process a single USD file."""
    print(f"Processing {os.path.basename(filepath)}...")

    layer = Sdf.Layer.FindOrOpen(filepath)
    if layer is None:
        print(f"  ERROR: Could not open {filepath}")
        return

    count = rename_chinese_prims(layer)
    if count > 0:
        layer.Save()
        print(f"  Renamed {count} Chinese-character prims")
    else:
        print(f"  No Chinese prims found")


def main():
    config_dir = os.path.join(ROBOT_DIR, "configuration")

    # Fix Chinese prims in both base and physics USDs
    for usd_file in ["robot_base.usd", "robot_physics.usd"]:
        filepath = os.path.join(config_dir, usd_file)
        if os.path.exists(filepath):
            process_file(filepath)

    # Fix imu_site broken reference
    base_path = os.path.join(config_dir, "robot_base.usd")
    if os.path.exists(base_path):
        fix_imu_site_reference(base_path)

    # Verify
    print("\nVerification:")
    stage = Usd.Stage.Open(os.path.join(ROBOT_DIR, "robot.usd"))
    chinese_count = 0
    for prim in stage.Traverse():
        if "金属" in str(prim.GetPath()):
            chinese_count += 1
    print(f"  Chinese prims remaining: {chinese_count}")
    print("Done.")


if __name__ == "__main__":
    main()
