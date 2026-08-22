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


class _DedicatedEndstopGCodeCommand:
    """Proxy a GCodeCommand and replace an upstream-only endstop suggestion."""

    def __init__(self, gcmd):
        self._gcmd = gcmd

    def __getattr__(self, name):
        return getattr(self._gcmd, name)

    def respond_info(self, msg, *args, **kwargs):
        # Upstream assumes the calibration switch is also stepper_z's homing
        # endstop. In dedicated-endstop mode that recommendation is wrong.
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
    """Use the configured sample count consistently for the switch-body touch."""

    def _probe_on_site(self, endstop, site, check_probe=False,
                       split_xy=False, wiggle=False, samples=None,
                       samples_result=None):
        # An older fork change hard-coded five samples for the rigid probe-body
        # measurement. Restore normal behaviour: use [z_calibration] samples
        # and samples_result for nozzle, switch body and bed reference alike.
        if check_probe and endstop is self.z_endstop:
            samples = self.helper.samples
            samples_result = self.helper.samples_result
        return super()._probe_on_site(
            endstop, site, check_probe=check_probe, split_xy=split_xy,
            wiggle=wiggle, samples=samples, samples_result=samples_result)


class ZCalibrationHelper(z_calibration_upstream.ZCalibrationHelper):
    def __init__(self, config):
        # Optional. If omitted, retain upstream endstop behaviour.
        self.calibration_endstop_pin = config.get(
            'calibration_endstop_pin', None)
        self.calibration_endstop = None

        # The base class registers klippy:connect using self.handle_connect and
        # CALIBRATE_Z using self.cmd_CALIBRATE_Z, so our overrides are used.
        super().__init__(config)

        if self.calibration_endstop_pin is not None:
            ppins = self.printer.lookup_object('pins')
            self.calibration_endstop = ppins.setup_pin(
                'endstop', self.calibration_endstop_pin)

            # Keep the dedicated switch visible in QUERY_ENDSTOPS.
            self.query_endstops.register_endstop(
                self.calibration_endstop, 'z_calibration')

            # probing_move() requires the Z steppers to be attached to this
            # endstop, mirroring Klipper's LookupZSteppers helper.
            self.printer.register_event_handler(
                'klippy:mcu_identify', self._handle_calibration_mcu_identify)

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
        # Let upstream locate the real stepper_z endstop and initialise all
        # normal probe parameters first.
        super().handle_connect()

        # Substitute only the endstop used internally by calibration. Normal
        # G28 Z continues to use the configured stepper_z endstop.
        if self.calibration_endstop is not None:
            self.z_endstop = z_calibration_upstream.EndstopWrapper(
                self.calibration_endstop)
            logging.info(
                "%s: using dedicated calibration_endstop_pin=%s; normal Z "
                "homing endstop is unchanged",
                self.config.get_name(), self.calibration_endstop_pin)

    def cmd_CALIBRATE_Z(self, gcmd):
        # Equivalent to upstream's dispatcher, but use the dedicated-endstop
        # aware CalibrationState and suppress the irrelevant homing-endstop
        # suggestion when a separate calibration switch is configured.
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
