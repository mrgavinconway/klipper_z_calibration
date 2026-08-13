import sys
import types
import unittest
from unittest import mock


mcu = types.ModuleType('mcu')
mcu.MCU_endstop = type('MCU_endstop', (), {})
sys.modules.setdefault('mcu', mcu)

import z_calibration


class _Toolhead:
    def get_position(self):
        return [0., 0., 10.]

    def get_last_move_time(self):
        return 0.


class _ProbeEndstop:
    def query_endstop(self, eventtime):
        return False

    def get_steppers(self):
        return []


class _Probe:
    def __init__(self):
        self.mcu_probe = _ProbeEndstop()

    def get_offsets(self):
        return [0., 0., 0.]

    def multi_probe_begin(self):
        pass

    def multi_probe_end(self):
        pass


class _Template:
    def run_gcode_from_command(self):
        pass


class _GCodeCommand:
    def __init__(self):
        self.messages = []

    def get_command(self):
        return 'CALIBRATE_Z'

    def respond_info(self, message):
        self.messages.append(message)

    def error(self, message):
        return RuntimeError(message)


class _Helper:
    samples = 3
    samples_result = 'average'
    tolerance = 1.
    retries = 0
    first_fast = False
    lift_speed = 20.
    speed = 50.
    position_min = -5.
    second_speed = 1.
    probing_speed = 3.
    retract_dist = 1.
    wiggle_offsets = None
    start_gcode = _Template()
    switch_gcode = _Template()
    end_gcode = _Template()
    position_z_endstop = 0.
    last_state = False
    last_z_offset = 0.

    def __init__(self, measurements=None):
        self.measurements = iter(measurements or [])
        self.probe_calls = 0

    def _move_safe_z(self, pos, speed):
        pass

    def _move(self, pos, speed):
        pass

    def _probe(self, gcmd, endstop, position_min, speed, wiggle=False):
        self.probe_calls += 1
        return [0., 0., next(self.measurements)]

    def _calc_mean(self, positions):
        return [sum(pos[i] for pos in positions) / len(positions)
                for i in range(3)]

    def _calc_median(self, positions):
        positions = sorted(positions, key=lambda pos: pos[2])
        return positions[len(positions) // 2]


def _sampling_state(measurements):
    state = z_calibration.CalibrationState.__new__(
        z_calibration.CalibrationState)
    state.helper = _Helper(measurements)
    state.gcmd = _GCodeCommand()
    state.toolhead = _Toolhead()
    state.probe = _Probe()
    return state


class ProbeBodySamplingTests(unittest.TestCase):
    def test_five_samples_select_median_despite_low_outlier(self):
        state = _sampling_state(
            [10.60675, 10.60675, 10.60550, 10.60675, 10.59800])

        result = state._probe_on_site(
            object(), [0., 0., None], samples=5,
            samples_result='median')

        self.assertEqual(5, state.helper.probe_calls)
        self.assertEqual(10.60675, result)

    def test_second_outlier_example_selects_expected_median(self):
        state = _sampling_state(
            [10.60050, 10.60300, 10.60175, 10.59925, 10.59425])

        result = state._probe_on_site(
            object(), [0., 0., None], samples=5,
            samples_result='median')

        self.assertEqual(5, state.helper.probe_calls)
        self.assertEqual(10.60050, result)

    def test_tolerance_retry_discards_set_and_takes_fresh_five_samples(self):
        state = _sampling_state([
            10.60000, 10.62000,
            10.60675, 10.60675, 10.60550, 10.60675, 10.59800,
        ])
        state.helper.tolerance = 0.015
        state.helper.retries = 1

        result = state._probe_on_site(
            object(), [0., 0., None], samples=5,
            samples_result='median')

        self.assertEqual(7, state.helper.probe_calls)
        self.assertEqual(10.60675, result)
        self.assertEqual(1, len(state.gcmd.messages))
        self.assertIn('Retrying', state.gcmd.messages[0])

    def test_only_probe_body_overrides_sampling_and_offset_is_unchanged(self):
        state = z_calibration.CalibrationState.__new__(
            z_calibration.CalibrationState)
        state.helper = _Helper()
        state.gcmd = _GCodeCommand()
        state.probe = _Probe()
        state.z_endstop = object()
        state.max_deviation = None
        state.offset_margins = [-1., 1.]
        state._add_probe_offset = lambda site: site
        state._set_new_gcode_offset = mock.Mock()
        measurements = iter([1.25, 10.60675, 9.90])
        state._probe_on_site = mock.Mock(
            side_effect=lambda *args, **kwargs: next(measurements))

        state.calibrate_z(0.465, [1., 2., None], [3., 4., None],
                          [5., 6., None])

        calls = state._probe_on_site.call_args_list
        self.assertEqual(3, len(calls))
        self.assertNotIn('samples', calls[0].kwargs)
        self.assertNotIn('samples_result', calls[0].kwargs)
        self.assertEqual(5, calls[1].kwargs['samples'])
        self.assertEqual('median', calls[1].kwargs['samples_result'])
        self.assertNotIn('samples', calls[2].kwargs)
        self.assertNotIn('samples_result', calls[2].kwargs)
        expected_offset = 9.90 - (10.60675 - 1.25 + 0.465)
        state._set_new_gcode_offset.assert_called_once_with(expected_offset)


if __name__ == '__main__':
    unittest.main()
