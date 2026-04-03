# Fixing the Lamp Base (scs215_v5) in Isaac Sim

## Problem

The lamp base mesh (`/World/LeLamp/scs215_v5/visuals/lamp_base`) was not staying fixed in place. Instead of being anchored to the ground/table, it moved with the articulation during simulation.

### Root Cause

`scs215_v5` was a **child body** of `joint_1` inside the PhysX articulation. The articulation solver treated it as a dynamic link and drove its position based on joint angles — even though physically it should be the stationary base of the lamp.

```
Articulation chain (before fix):
  root_joint (fixed) → lamparm__base_elbow
    ├── joint_2 → lamparm__wrist_head
    │   └── joint_1 → scs215_v5  ← PROBLEM: dynamic body, moves with joint
    └── joint_3 → lamparm__elbow_wrist → ... → diffuser
```

## Solution

Three changes in `robot/configuration/robot_physics.usd`:

### 1. Make scs215_v5 kinematic

```python
scs = stage.GetPrimAtPath('/simulation/scs215_v5')
rb = UsdPhysics.RigidBodyAPI.Apply(scs)
rb.GetKinematicEnabledAttr().Set(True)
```

**What this does:** Tells PhysX that `scs215_v5` is a scripted/fixed body — physics forces and gravity don't affect it.

**Why needed:** Without this, even if excluded from the articulation, `scs215_v5` would fall under gravity as a free rigid body.

### 2. Exclude joint_1 from the articulation

```python
j1 = stage.GetPrimAtPath('/simulation/joints/joint_1')
j1.GetAttribute('physics:excludeFromArticulation').Set(True)
```

**What this does:** Removes `joint_1` from the articulation solver. It still exists as a physics constraint between `lamparm__wrist_head` and `scs215_v5`, but PhysX no longer treats `scs215_v5` as part of the articulation tree.

**Why needed:** A kinematic body cannot be a child in an articulation joint. Without exclusion, PhysX would either error or produce unstable behavior trying to reconcile the kinematic constraint with the articulation solver.

### 3. Exclude imu_site_frame from the articulation

```python
imu_j = stage.GetPrimAtPath('/simulation/joints/imu_site_frame')
imu_j.GetAttribute('physics:excludeFromArticulation').Set(True)
```

**What this does:** Also removes the IMU sensor's fixed joint from the articulation.

**Why needed:** `imu_site` is a child of `scs215_v5` via `imu_site_frame`. Since `scs215_v5` is now outside the articulation, its child joint must also be excluded to keep the articulation tree consistent.

## Result

```
After fix:

Articulation tree (joints 2-5 active):
  root_joint (fixed) → lamparm__base_elbow
    ├── joint_2 → lamparm__wrist_head
    └── joint_3 → lamparm__elbow_wrist
        └── joint_4 → lamparm__wrist_head_2
            └── joint_5 → diffuser

Excluded from articulation (static):
  joint_1 → scs215_v5 (kinematic, fixed in place)
    └── imu_site_frame → imu_site (excluded)
```

- `scs215_v5` with `lamp_base` mesh stays fixed on the ground/table
- Joints 2-5 drive the arm and lamp head normally
- `joint_1` (base_yaw) still acts as a constraint but outside the articulation solver

## Files Modified

- `robot/configuration/robot_physics.usd` — all three changes applied here

## How to Verify

```python
from pxr import Usd, UsdPhysics

stage = Usd.Stage.Open('robot/robot.usd')

# Check scs215_v5 is kinematic
scs = stage.GetPrimAtPath('/simulation/scs215_v5')
rb = UsdPhysics.RigidBodyAPI(scs)
assert rb.GetKinematicEnabledAttr().Get() == True

# Check joint_1 excluded
j1 = stage.GetPrimAtPath('/simulation/joints/joint_1')
assert j1.GetAttribute('physics:excludeFromArticulation').Get() == True

# Check imu_site_frame excluded
imu = stage.GetPrimAtPath('/simulation/joints/imu_site_frame')
assert imu.GetAttribute('physics:excludeFromArticulation').Get() == True
```

## Important Notes

- Do NOT reverse joint_1 body0/body1 direction — this breaks the articulation dynamics and requires negating joint angle signs
- Do NOT set `physxArticulation:fixBase` on the root_joint — the original URDF structure with `lamparm__base_elbow` as root works correctly
- Do NOT modify joint limits or orientations in robot_base.usd — keep the original URDF import values
- If re-importing the URDF, this fix must be re-applied to robot_physics.usd
