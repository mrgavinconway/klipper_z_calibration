# Dedicated calibration endstop support

This fork adds an optional `calibration_endstop_pin` setting to `[z_calibration]`.

Upstream `klipper_z_calibration` uses the printer's normal `stepper_z` endstop for both Z homing and automatic Z calibration. With this fork, those can be separate:

- the normal `[stepper_z] endstop_pin` is still used by `G28 Z` and is not modified;
- `calibration_endstop_pin` is used only by `CALIBRATE_Z` and `PROBE_Z_ACCURACY`.

If `calibration_endstop_pin` is omitted, behaviour is identical to upstream.

## Voron V0 / detachable ZeroClick example

The following matches the geometry this fork was created for:

```ini
[stepper_z]
# Existing frame-mounted Z microswitch remains the normal Z homing datum.
endstop_pin: ^PC6

[z_calibration]
# Dedicated bed-mounted reference microswitch.
calibration_endstop_pin: ^PA3

# Nozzle presses the dedicated reference switch here.
nozzle_xy_position: 4.5, 42

# With ZeroClick attached, a rigid part of the probe microswitch body presses
# the same dedicated reference switch here.
switch_xy_position: 25, 26.5

# Physical bed point to probe with ZeroClick. Probe X/Y offsets are applied by
# klipper_z_calibration automatically.
bed_xy_position: 71, 63.5

# Calibrate this value for the actual rigid-body contact geometry.
switch_offset: 0.5

safe_z_height: 30
samples: 3
samples_tolerance: 0.015
samples_tolerance_retries: 3
samples_result: median
probing_speed: 3
probing_second_speed: 1
probing_retract_dist: 1

# The detachable probe must be absent for the nozzle measurement.
start_gcode:
    DETACH_PROBE

# Attach it after the nozzle measurement and before the rigid body / bed
# measurements.
before_switch_gcode:
    ATTACH_PROBE

end_gcode:
    DETACH_PROBE
```

The `switch_offset` value above is only a placeholder. It must be calibrated for the actual printer before relying on the resulting Z offset.

## Important pin rule

A pin configured as `calibration_endstop_pin` must not also be configured as a `[gcode_button]`, `[probe]`, normal endstop, or any other Klipper pin user. For the example above, remove the old:

```ini
[gcode_button bed_switch]
pin: PA3
```

The dedicated calibration switch is registered with Klipper's `QUERY_ENDSTOPS` command as `z_calibration`, so its electrical state can still be checked without a `gcode_button`.

## Installation

Clone this fork and run its installer as normal:

```bash
cd ~
git clone https://github.com/mrgavinconway/klipper_z_calibration.git
cd klipper_z_calibration
./install.sh
```

The installer links the unchanged upstream implementation internally as `z_calibration_upstream.py` and installs this fork's wrapper as Klipper's `z_calibration.py`. Existing `[z_calibration]` section names and `CALIBRATE_Z` commands therefore remain unchanged.

The Moonraker update-manager origin created by this fork points at `mrgavinconway/klipper_z_calibration`.
