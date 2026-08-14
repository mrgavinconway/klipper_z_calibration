import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest import mock


mcu = types.ModuleType('mcu')
mcu.MCU_endstop = type('MCU_endstop', (), {})
sys.modules.setdefault('mcu', mcu)

import z_calibration


PACKAGE = 'z_calibration_test_package'
package = types.ModuleType(PACKAGE)
package.__path__ = []
sys.modules.setdefault(PACKAGE, package)
sys.modules.setdefault(PACKAGE + '.z_calibration_upstream', z_calibration)
spec = importlib.util.spec_from_file_location(
    PACKAGE + '.z_calibration_separate',
    Path(__file__).parents[1] / 'z_calibration_separate.py')
z_calibration_separate = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = z_calibration_separate
spec.loader.exec_module(z_calibration_separate)


class _GCodeCommand:
    def __init__(self):
        self.messages = []

    def get_command(self):
        return 'CALIBRATE_Z'

    def respond_info(self, message):
        self.messages.append(message)

    def error(self, message):
        return RuntimeError(message)


class _ValidationHelper:
    expected_bed_probe_z = 9.919
    bed_probe_max_deviation = 0.100
    bed_probe_check_mode = 'warn'
    expected_nozzle_switch_delta = 9.470
    nozzle_switch_max_deviation = 0.075
    last_bed_probe_z = None
    last_nozzle_switch_delta = None


def _validation_state(helper=None):
    state = z_calibration_separate.CalibrationState.__new__(
        z_calibration_separate.CalibrationState)
    state.helper = helper or _ValidationHelper()
    state.gcmd = _GCodeCommand()
    return state


class ReferenceValidationTests(unittest.TestCase):
    def test_absolute_bed_deviation_can_warn_while_relative_check_passes(self):
        state = _validation_state()

        state._validate_reference_measurements(1.077, 10.545, 10.040)

        self.assertEqual(1, len(state.gcmd.messages))
        self.assertIn('bed probe sanity warning', state.gcmd.messages[0])
        self.assertAlmostEqual(10.040, state.helper.last_bed_probe_z)
        self.assertAlmostEqual(9.468, state.helper.last_nozzle_switch_delta)

    def test_absolute_bed_deviation_still_fails_in_error_mode(self):
        helper = _ValidationHelper()
        helper.bed_probe_check_mode = 'error'
        state = _validation_state(helper)

        with self.assertRaisesRegex(RuntimeError,
                                    'bed probe sanity check failed'):
            state._validate_reference_measurements(1.077, 10.545, 10.040)

    def test_relative_geometry_remains_a_hard_failure_in_warn_mode(self):
        state = _validation_state()

        with self.assertRaisesRegex(RuntimeError,
                                    'nozzle/switch geometry sanity check'):
            state._validate_reference_measurements(1.000, 10.600, 10.040)


class CalibrationRetryTests(unittest.TestCase):
    def _helper(self):
        helper = z_calibration_separate.ZCalibrationHelper.__new__(
            z_calibration_separate.ZCalibrationHelper)
        helper.last_state = False
        helper.z_homing = 0.
        helper.calibration_endstop = None
        helper.calibration_retries = 1
        helper.printer = types.SimpleNamespace(command_error=RuntimeError)
        helper._get_nozzle_site = mock.Mock(return_value=[1., 2., None])
        helper._get_switch_site = mock.Mock(return_value=[3., 4., None])
        helper._get_bed_site = mock.Mock(return_value=[5., 6., None])
        helper._get_switch_offset = mock.Mock(return_value=0.55)
        helper._log_params = mock.Mock()
        return helper

    @mock.patch.object(z_calibration_separate, 'CalibrationState')
    def test_retries_known_quality_failure_once(self, state_class):
        failed = mock.Mock()
        failed.calibrate_z.side_effect = RuntimeError(
            'CALIBRATE_Z: offset 0.200 is outside the configured range')
        passed = mock.Mock()
        state_class.side_effect = [failed, passed]
        helper = self._helper()
        gcmd = _GCodeCommand()

        helper.cmd_CALIBRATE_Z(gcmd)

        self.assertEqual(2, state_class.call_count)
        self.assertEqual(1, len(gcmd.messages))
        self.assertIn('Retrying the complete calibration', gcmd.messages[0])

    @mock.patch.object(z_calibration_separate, 'CalibrationState')
    def test_does_not_retry_motion_failure(self, state_class):
        state_class.return_value.calibrate_z.side_effect = RuntimeError(
            'No trigger on probe after full movement')
        helper = self._helper()

        with self.assertRaisesRegex(RuntimeError, 'No trigger on probe'):
            helper.cmd_CALIBRATE_Z(_GCodeCommand())

        self.assertEqual(1, state_class.call_count)


if __name__ == '__main__':
    unittest.main()
