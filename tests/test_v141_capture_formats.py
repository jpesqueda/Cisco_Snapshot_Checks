"""Regression cases reconstructed from redacted Catalyst output examples."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from snapshotchecks.comparison import compare_snapshots, load_rules
from snapshotchecks.parsing import TextFSMResult, env_parser, parse_capture
from snapshotchecks.pending_normalizers import auth_sessions, interface_link
from snapshotchecks.storage import command_block

ENV = 'show environment all'
LINK = 'show interfaces link'
AUTH = 'show authentication sessions'


def sensor_table(temperature=45, state='Normal', alarms=0):
    def row(sensor, location, state, reading):
        return f'{sensor:<20}{location:<12}{state:<14}{reading}'
    return '\n'.join((
        f'Number of Critical alarms: {alarms}',
        'Number of Major alarms: 0',
        'Number of Minor alarms: 0',
        '',
        'Sensor List: Environmental Monitoring',
        row('Sensor', 'Location', 'State', 'Reading       Threshold(Minor,Major,Critical,Shutdown)'),
        row('Temp: Coretemp', 'R0', state, f'  {temperature} Celsius   (107,117,123,125)(Celsius)'),
        row('Temp:   Outlet', 'R0', 'Normal', '  40 Celsius   (63,73,103,105)(Celsius)'),
        row('V1: VX1', 'R0', 'Normal', '  873 mV       na'),
        row('V1: VX1', '3/0', 'Normal', '  900 mV       na'),
        row('HotSwap: Volts', 'R0', 'Normal', '  53 V DC      na'),
    ))


def link_table(up_time='1w0d', down_time='34w1d', first_down=False):
    def row(port, name, down, up=''):
        return f'{port:<14}{name:<20}{down:<14}{up}'.rstrip()
    return '\n'.join((
        row('Port', 'Name', 'Down Time', 'Up Time'),
        row('Gi1/0/1', '', '1m' if first_down else '00:00:00', '' if first_down else up_time),
        row('Te10/0/25', 'UNUSED PORT', down_time),
    ))


class CaptureFormatTests(unittest.TestCase):
    def test_sensors_at_distinct_locations_and_alarm_counts(self):
        parsed = env_parser(sensor_table(), None)
        self.assertEqual(len(parsed), 8)
        self.assertEqual(parsed['sensor r0 / temp: outlet'], 'NORMAL')
        self.assertEqual(parsed['sensor r0 / v1: vx1'], 'NORMAL')
        self.assertEqual(parsed['sensor 3/0 / v1: vx1'], 'NORMAL')
        self.assertEqual(parsed['alarm major'], 0)

    def test_legacy_and_invalid_sensor_data(self):
        self.assertEqual(env_parser('Switch 1 FAN 1 is OK', None), {'switch 1 fan 1': 'OK'})
        with self.assertRaises(ValueError):
            env_parser(sensor_table() + '\nGi1/0/2 garbage', None)

    def test_link_timer_columns_take_priority_over_template_rows(self):
        misleading = [{'port': 'Gi1/0/1', 'status': 'down'}]
        parsed = interface_link(link_table(), misleading)
        self.assertEqual(parsed, {
            'GigabitEthernet1/0/1': {'link_table_state': 'up'},
            'TenGigabitEthernet10/0/25': {'link_table_state': 'down'},
        })

    def test_ambiguous_link_does_not_become_pass(self):
        with self.assertRaisesRegex(ValueError, 'Ambiguous link timers'):
            interface_link(link_table(up_time='00:00:00'), None)

    def test_authentication_no_sessions_and_nonempty_table(self):
        for line in ('No sessions currently exist', 'No authentication sessions match supplied criteria.'):
            with self.subTest(line=line):
                self.assertEqual(auth_sessions(line, None), {'has_sessions': False})
        self.assertTrue(auth_sessions('', [{'interface': 'Gi1/0/1', 'status': 'Authorized'}])['has_sessions'])
        with self.assertRaises(ValueError):
            auth_sessions('Unexpected output', None)

    def test_end_to_end_expected_and_unexpected_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            def capture(snapshot, environment, links, auth='No sessions currently exist'):
                path = Path(directory) / f'{snapshot}.txt'
                path.write_text('HOSTNAME: LAB-SW01\n' + command_block(ENV, environment)
                                + command_block(LINK, links) + command_block(AUTH, auth),
                                encoding='utf-8')
                with patch('snapshotchecks.parsing.textfsm_parse', return_value=TextFSMResult()):
                    parsed = parse_capture(path, snapshot=snapshot)
                return parsed

            pre = capture('002', sensor_table(), link_table())
            post = capture('003', sensor_table(temperature=49), link_table('00:04:18', '21w1d'))
            for snapshot in (pre, post):
                self.assertEqual({entry['status'] for entry in snapshot['coverage'].values()}, {'NORMALIZED'})
            rules = load_rules(None)
            unchanged = compare_snapshots(pre, post, rules)
            for section in ('hardware', 'interfaces', 'security'):
                self.assertEqual(unchanged['sections'][section]['status'], 'PASS')

            changed = capture('004', sensor_table(state='Critical', alarms=1), link_table(first_down=True))
            report = compare_snapshots(pre, changed, rules)
            self.assertEqual(report['sections']['hardware']['status'], 'CHANGE')
            self.assertEqual(report['sections']['interfaces']['status'], 'CHANGE')
            self.assertEqual(report['sections']['security']['status'], 'PASS')

            unknown = capture('005', sensor_table(), link_table(up_time='00:00:00'))
            self.assertEqual(unknown['coverage'][LINK]['status'], 'PARSE_ERROR')
            self.assertNotIn('interfaces', unknown['model'])
