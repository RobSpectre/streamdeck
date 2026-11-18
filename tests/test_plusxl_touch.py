import unittest
from unittest.mock import patch
from tools.plusxl_touch import decode, forwardable, affected_version, DEVICE


class PlusXLTouchTests(unittest.TestCase):
    def test_real_left_and_right_reports(self):
        for report, position, x, y in [('01020e0001014e003a0000000000', 0, 78, 58),
                                       ('01020e00010168042c0000000000', 5, 128, 44)]:
            self.assertEqual(decode(bytes.fromhex(report)),
                             {'device': DEVICE, 'position': position, 'x': x, 'y': y, 'hold': False})

    def test_boundaries_and_non_taps(self):
        for x in [0,199,200,399,400,599,600,799,800,999,1000,1199,1200]:
            report = bytes([1,2,14,0,1,1])+x.to_bytes(2,'little')+bytes([50,0])
            result = decode(report)
            self.assertEqual(result['position'] if result else None, x//200 if x<1200 else None)
        for report in [b'', bytes.fromhex('01020e0002014e003a00'), bytes.fromhex('01020e0003014e003a00'),
                       bytes.fromhex('01030e0001014e003a00'), bytes.fromhex('01020e0001014e006400')]:
            self.assertIsNone(decode(report))

    def test_only_fresh_visible_dial_can_forward(self):
        event = {'payload': {'device': DEVICE, 'position': 0}, 'observed': 10}
        visible = {DEVICE+'.01 - broadcast.Encoder.0.0': {'kind':'dial'}}
        self.assertTrue(forwardable(event, visible, 11))
        self.assertFalse(forwardable(event, {}, 11))
        self.assertFalse(forwardable(event, visible, 13))
        self.assertFalse(forwardable(event, visible, 9))
        self.assertFalse(forwardable(event, {'other.01 - broadcast.Encoder.0.0': {'kind':'dial'}}, 11))

    def test_upgrade_disables_workaround(self):
        for version, enabled in [('2.14.0', True), ('2.14.0-1', True), ('2.14.1', False), ('2.15.0', False)]:
            with patch('tools.plusxl_touch.subprocess.check_output', return_value=version):
                self.assertEqual(affected_version(), enabled)
