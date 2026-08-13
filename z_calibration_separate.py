# Klipper z_calibration wrapper with support for a dedicated calibration endstop.
#
# This fork keeps the printer's normal Z endstop for G28 Z and optionally uses
# a second physical endstop only for CALIBRATE_Z / PROBE_Z_ACCURACY.
#
# Copyright (C) 2026 Gavin Conway / OpenAI-assisted changes
# Upstream code copyright remains with its original authors.
# Distributed under the GNU GPLv3, matching the upstream project.

import logging

from . import z_calibration_upstream


# Dedicated-endstop reference geometry for this Voron V0 / ZeroClick setup.
# Command-line NOZZLE_POSITION / SWITCH_POSITION parameters still override
# these values for one-off testing.
DEDICATED_NOZZLE_SITE = [3.5, 39.5, None]
DEDICATED_SWITCH_SITE = [17.0, 25.0, None]


class _DedicatedEndstopGCodeCommand:
    """Proxy a GCodeCommand and replace an upstream-only endstop suggestion."""

    def __init__(self, gcmd):
        self._gcmd = gcmd

    def __getattr__(self, name):
        return getattr(self._gcmd, name)

    def respond_info(self, msg, *args, **kwargs):
        # Upstream assumes the calibration switch is also stepper_z's homing
        # endstop.  In dedicated-endstop mode that recommendation is wrong:
        # the real homing endstop must remain unchanged.
        if ("POSSIBLE SUGGESTION" in msg
                and "position_endstop" in msg):
            self._gcmd.respond_info(
                "%s: dedicated calibration endstop in use; runtime Z offset "
                "will be applied and the normal stepper_z position_endstop "
                "must remain unchanged"
                % (self._gcmd.get_command()), *args, **kwargs)
            return
        self._gcmd.respond_info(msg, *args, **kwargs)


class CalibrationState(z_calibration_upstream.CalibrationState):
    """Upstream calibration state with optional plausibility checks."""

    def __init__(self, helper, gcmd):
        super().__init__(helper, gcmd)
        self._reference_measurements = []

    def _probe_on_site(self, *args, **kwargs):
        result = super()._probe_on_site(*args, **kwargs)
        self._reference_measurements.append(result)

        # CALIBRATE_Z calls _probe_on_site in this order:
        #   1. nozzle -> dedicated switch
        #   2. rigid probe body -> dedicated switch
        #   3. probe -> bed
        # Validate only after all three successful measurements are available,
        # and before upstream calculates/applies the runtime Z offset.
        if len(self._reference_measurements) == 3:
            nozzle_zero, switch_zero, probe_zero = self._reference_measurements
            self._validate_reference_measurements(
                nozzle_zero, switch_zero, probe_zero)
        return result

    def _validate_reference_measurements(self, nozzle_zero, switch_zero,
                                         probe_zero):
        helper = self.helper
        nozzle_switch_delta = switch_zero - nozzle_zero
        helper.last_bed_probe_z = probe_zero
        helper.last_nozzle_switch_delta = nozzle_switch_delta

        if helper.expected_bed_probe_z is not None:
            deviation = abs(probe_zero - helper.expected_bed_probe_z)
            if deviation > helper.bed_probe_max_deviation:
                raise self.gcmd.error(
                    "%s: bed probe sanity check failed: measured=%.3f, "
                    "expected=%.3f, deviation=%.3f > allowed=%.3f"
                    % (self.gcmd.get_command(), probe_zero,
                       helper.expected_bed_probe_z, deviation,
                       helper.bed_probe_max_deviation))

        if helper.expected_nozzle_switch_delta is not None:
            deviation = abs(nozzle_switch_delta
                            - helper.expected_nozzle_switch_delta)
            if deviation > helper.nozzle_switch_max_deviation:
                raise self.gcmd.error(
                    "%s: nozzle/switch geometry sanity check failed: "
                    "measured_delta=%.3f, expected_delta=%.3f, "
                    "deviation=%.3f > allowed=%.3f. Check for filament on "
                    "the nozzle and verify the probe is seated correctly."
                    % (self.gcmd.get_command(), nozzle_switch_delta,
                       helper.expected_nozzle_switch_delta, deviation,
                       helper.nozzle_switch_max_deviation))


class ZCalibrationHelper(z_calibration_upstream.ZCalibrationHelper):
    def __init__(self, config):
        # Optional. If omitted, retain upstream behaviour and use stepper_z's
        # configured endstop for calibration.
        self.calibration_endstop_pin = config.get(
            'calibration_endstop_pin', None)
        self.calibration_endstop = None

        # Optional absolute/relative plausibility checks.  They deliberately
        # default to disabled because a useful expected value is printer- and
        # temperature-specific.  If an expected value is configured, the
        # associated default tolerance is intentionally conservative.
        self.expected_bed_probe_z = config.getfloat(
            'expected_bed_probe_z', None)
        self.bed_probe_max_deviation = config.getfloat(
            'bed_probe_max_deviation', 0.100, above=0.)
        self.expected_nozzle_switch_delta = config.getfloat(
            'expected_nozzle_switch_delta', None)
        self.nozzle_switch_max_deviation = config.getfloat(
            'nozzle_switch_max_deviation', 0.150, above=0.)

        self.last_bed_probe_z = None
        self.last_nozzle_switch_delta = None

        # The base class registers klippy:connect using self.handle_connect;
        # because this class overrides it, our override is what is registered.
        # It also registers CALIBRATE_Z using self.cmd_CALIBRATE_Z, so the
        # override below is registered automatically.
        super().__init__(config)

        if self.calibration_endstop_pin is not None:
            ppins = self.printer.lookup_object('pins')
            self.calibration_endstop = ppins.setup_pin(
                'endstop', self.calibration_endstop_pin)

            # Make the dedicated switch visible in QUERY_ENDSTOPS as
            # "z_calibration". It must not also be configured as a
            # [gcode_button] or any other pin user.
            self.query_endstops.register_endstop(
                self.calibration_endstop, 'z_calibration')

            # A probing_move() endstop must have the Z steppers attached to it.
            # This mirrors Klipper's LookupZSteppers helper used by [probe].
            self.printer.register_event_handler(
                'klippy:mcu_identify', self._handle_calibration_mcu_identify)

    def get_status(self, eventtime):
        status = super().get_status(eventtime)
        status.update({
            'last_bed_probe_z': self.last_bed_probe_z,
            'last_nozzle_switch_delta': self.last_nozzle_switch_delta,
        })
        return status

    def _handle_calibration_mcu_identify(self):
        if self.calibration_endstop is None:
            return
        kin = self.printer.lookup_object('toolhead').get_kinematics()
        z_steppers = [s for s in kin.get_steppers()
                      if s.is_active_axis('z')]
        if not z_steppers:
            raise self.printer.config_error(
                "No Z steppers found for dedicated z_calibration endstop")
        for stepper in z_steppers:
            self.calibration_endstop.add_stepper(stepper)

    def handle_connect(self):
        # Let upstream locate the real stepper_z endstop and initialise probe
        # parameters. That endstop remains untouched and continues to be used
        # for normal Z homing.
        super().handle_connect()

        # After upstream setup, substitute only the endstop used internally by
        # the calibration measurements.
        if self.calibration_endstop is not None:
            self.z_endstop = z_calibration_upstream.EndstopWrapper(
                self.calibration_endstop)
            logging.info(
                "%s: using dedicated calibration_endstop_pin=%s; normal Z "
                "homing endstop is unchanged",
                self.config.get_name(), self.calibration_endstop_pin)

    def _get_nozzle_site(self, gcmd):
        # For the dedicated calibration switch, use this fork's measured
        # machine geometry. An explicit command parameter remains available
        # for one-off positioning tests.
        if (self.calibration_endstop_pin is not None
                and not gcmd.get("NOZZLE_POSITION", "")):
            return list(DEDICATED_NOZZLE_SITE)
        return super()._get_nozzle_site(gcmd)

    def _get_switch_site(self, gcmd, nozzle_site):
        # Same rule for the rigid ZeroClick body contact point.
        if (self.calibration_endstop_pin is not None
                and not gcmd.get("SWITCH_POSITION", "")):
            return list(DEDICATED_SWITCH_SITE)
        return super()._get_switch_site(gcmd, nozzle_site)

    def cmd_CALIBRATE_Z(self, gcmd):
        # This is intentionally kept equivalent to upstream's short dispatcher,
        # but uses our CalibrationState so we can validate the three reference
        # measurements before any runtime Z offset is applied.
        self.last_state = False
        if self.z_homing is None:
            raise gcmd.error("%s: must home axes first"
                             % (gcmd.get_command()))
        nozzle_site = self._get_nozzle_site(gcmd)
        switch_site = self._get_switch_site(gcmd, nozzle_site)
        bed_site = self._get_bed_site(gcmd)
        switch_offset = self._get_switch_offset(gcmd)
        self._log_params(gcmd, switch_offset, nozzle_site, switch_site,
                         bed_site)

        state_gcmd = gcmd
        if self.calibration_endstop is not None:
            state_gcmd = _DedicatedEndstopGCodeCommand(gcmd)
        state = CalibrationState(self, state_gcmd)
        state.calibrate_z(switch_offset, nozzle_site, switch_site, bed_site)


def load_config(config):
    return ZCalibrationHelper(config)
