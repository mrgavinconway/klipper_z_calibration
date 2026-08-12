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


class ZCalibrationHelper(z_calibration_upstream.ZCalibrationHelper):
    def __init__(self, config):
        # Optional. If omitted, retain upstream behaviour and use stepper_z's
        # configured endstop for calibration.
        self.calibration_endstop_pin = config.get(
            'calibration_endstop_pin', None)
        self.calibration_endstop = None

        # The base class registers klippy:connect using self.handle_connect;
        # because this class overrides it, our override is what is registered.
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


def load_config(config):
    return ZCalibrationHelper(config)
