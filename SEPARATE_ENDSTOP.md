# Dedicated calibration endstop support

This fork keeps the upstream `klipper_z_calibration` workflow and adds one feature: an optional dedicated physical endstop used only for automatic Z calibration.

- the normal `[stepper_z] endstop_pin` remains the `G28 Z` homing datum;
- `calibration_endstop_pin` is used by `CALIBRATE_Z` and `PROBE_Z_ACCURACY`;
- the normal upstream `offset_margins` check remains the final safety bound.

The fork deliberately does **not** add nozzle-conditioning loops, absolute bed-Z baselines, extra nozzle/probe-body geometry gates, or whole-calibration retry logic. Those are better kept as commissioning/diagnostic tools rather than mandatory print-start checks.

When a dedicated calibration endstop is configured, the fork also suppresses upstream's `POSSIBLE SUGGESTION` to alter `stepper_z position_endstop`, because that recommendation only applies when the calibration switch is also the Z homing switch.

## Voron V0 / detachable ZeroClick example

```ini
[stepper_z]
# Existing frame-mounted Z microswitch remains the normal Z homing datum.
endstop_pin: ^PC6

[z_calibration]
# Dedicated bed-mounted reference microswitch.
calibration_endstop_pin: ^PA3

# Bare nozzle presses the dedicated reference switch here.
nozzle_xy_position: 3.5, 39.5

# With ZeroClick attached, a rigid part of the probe body presses the same
# dedicated reference switch here.
switch_xy_position: 24, 25

# Physical bed point to probe with ZeroClick.
bed_xy_position: 71, 63.5

# Calibrated mechanical constant.
switch_offset: 0.550

# Final calculated Z correction must stay inside this range.
offset_margins: -0.100,0.100

safe_z_height: 15
samples: 3
samples_result: median
samples_tolerance: 0.015
samples_tolerance_retries: 3
probing_first_fast: true
probing_speed: 5
probing_second_speed: 1
probing_retract_dist: 1

start_gcode:
    DETACH_PROBE

before_switch_gcode:
    ATTACH_PROBE

end_gcode:
    DETACH_PROBE
```

The configured `samples` and `samples_result` are used consistently for the nozzle, rigid probe-body and bed-reference measurements. `PROBE_Z_ACCURACY` remains available for diagnostic repeatability testing.

## Nozzle cleanliness

Automatic Z calibration assumes that the nozzle physically touching the reference switch represents the real metal nozzle tip. A physical nozzle brush/wiper before calibration is the preferred way to handle normal ooze. This fork does not try to compensate for contamination by adding many sacrificial measurement touches.

## Important pin rule

A pin configured as `calibration_endstop_pin` must not also be configured as a `[gcode_button]`, `[probe]`, normal endstop, or any other Klipper pin user.

The dedicated calibration switch is registered with `QUERY_ENDSTOPS` as `z_calibration`, so its electrical state can still be inspected without a `gcode_button`.

## Installation

```bash
cd ~
git clone https://github.com/mrgavinconway/klipper_z_calibration.git
cd klipper_z_calibration
./install.sh
```

The installer links the upstream implementation internally as `z_calibration_upstream.py` and installs this fork's wrapper as Klipper's `z_calibration.py`. Existing `[z_calibration]` section names and `CALIBRATE_Z` commands remain unchanged.

The Moonraker update-manager origin points at `mrgavinconway/klipper_z_calibration`.
