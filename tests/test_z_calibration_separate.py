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

    def respond_info(self, message, *args, **kwargs):
        self.messages.append(message)

    def error(self, message):
        return RuntimeError(message)


class DedicatedEndstopMessageTests(unittest.TestCase):
    def test_replaces_upstream_position_endstop_suggestion(self):
        gcmd = _GCodeCommand()
        proxy = z_calibration_separate._DedicatedEndstopGCodeCommand(gcmd)

        proxy.respond_info(
            'CALIBRATE_Z: POSSIBLE SUGGESTION: new z axis position_endstop=1')

        self.assertEqual(1, len(gcmd.messages))
        self.assertIn('normal stepper_z position_endstop must remain unchanged',
                      gcmd.messages[0])

    def test_passes_normal_messages_through(self):
        gcmd = _GCodeCommand()
        proxy = z_calibration_separate._DedicatedEndstopGCodeCommand(gcmd)

        proxy.respond_info('normal calibration message')

        self.assertEqual(['normal calibration message'], gcmd.messages)


class BodySamplingTests(unittest.TestCase):
    def _state(self):
        state = z_calibration_separate.CalibrationState.__new__(
            z_calibration_separate.CalibrationState)
        state.z_endstop = object()
        state.helper = types.SimpleNamespace(
            samples=3,
            samples_result='median',
        )
        return state

    def test_switch_body_uses_configured_sample_count(self):
        state = self._state()

        with mock.patch.object(
                z_calibration.CalibrationState, '_probe_on_site',
                return_value=10.5) as upstream_probe:
            result = state._probe_on_site(
                state.z_endstop, [24., 25., None], check_probe=True,
                samples=5, samples_result='median')

        self.assertEqual(10.5, result)
        upstream_probe.assert_called_once_with(
            state.z_endstop, [24., 25., None], check_probe=True,
            split_xy=False, wiggle=False, samples=3,
            samples_result='median')

    def test_nozzle_measurement_keeps_normal_arguments(self):
        state = self._state()

        with mock.patch.object(
                z_calibration.CalibrationState, '_probe_on_site',
                return_value=1.0) as upstream_probe:
            state._probe_on_site(
                state.z_endstop, [3.5, 39.5, None], check_probe=False,
                split_xy=True, wiggle=True)

        upstream_probe.assert_called_once_with(
            state.z_endstop, [3.5, 39.5, None], check_probe=False,
            split_xy=True, wiggle=True, samples=None,
            samples_result=None)


if __name__ == '__main__':
    unittest.main()
