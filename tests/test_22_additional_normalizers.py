"""Regression coverage for the 22 existing TextFSM templates that lacked semantic mappers.

The tests exercise deterministic, built-in fallback normalization against the
provided simulated PRE/POST. They do NOT certify TextFSM's installed engine.
"""
from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from snapshotchecks.parsing import NORMALIZERS, extract_commands, parse_capture
from snapshotchecks.comparison import compare_snapshots, load_rules

ROOT=Path(__file__).resolve().parents[1]
PRE=ROOT/'examples/C9300-ACCESS-01_PRE_SIMULATED.txt'
POST=ROOT/'examples/C9300-ACCESS-01_POST_SIMULATED.txt'
ADDITIONAL=[
 'show clock','show module','show license summary','show interfaces counters',
 'show spanning-tree summary','show interfaces link','show interfaces transceiver detail',
 'show mac address-table','show mac address-table count','show ip arp',
 'show ip route summary','show ip protocols','show cdp neighbors',
 'show cdp neighbors detail','show lldp neighbors','show lldp neighbors detail',
 'show authentication sessions','show ip dhcp snooping binding',
 'show device-tracking database','show processes cpu sorted',
 'show processes memory sorted','show logging',
]

class AdditionalNormalizersTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pre=parse_capture(PRE,snapshot='001')
        cls.post=parse_capture(POST,snapshot='002')
        cls.rules=load_rules(ROOT/'compare_rules.yaml')

    def test_exactly_22_new_commands_are_registered_and_normalized(self):
        self.assertEqual(len(ADDITIONAL),22)
        for command in ADDITIONAL:
            with self.subTest(command=command):
                self.assertIn(command,NORMALIZERS)
                self.assertEqual(self.pre['coverage'][command]['status'],'NORMALIZED')
                self.assertEqual(self.post['coverage'][command]['status'],'NORMALIZED')

    def test_capture_coverage_and_no_false_upgrade_changes(self):
        self.assertEqual(len(self.pre['coverage']),43)
        self.assertEqual(len(self.post['coverage']),43)
        self.assertEqual(sum(x['status']=='NORMALIZED' for x in self.pre['coverage'].values()),42)
        self.assertEqual(self.pre['coverage']['show running-config']['status'],'SKIPPED_SENSITIVE')
        report=compare_snapshots(self.pre,self.post,self.rules,'17.5.6')
        self.assertEqual(report['overall_status'],'INCOMPLETE')
        self.assertEqual(report['sections']['system']['status'],'EXPECTED')
        self.assertTrue(all(r['status']!='CHANGE' for section in report['sections'].values() for r in section['rows']))

    def test_normalized_models_are_not_raw_counters_or_logs(self):
        model=self.pre['model']
        self.assertNotIn('message_lines',str(model).lower())
        self.assertNotIn('REPLACE_ME',str(model))
        self.assertNotIn('uptime',str(model).lower())
        self.assertEqual(model['system']['time_source'],'NTP')
        self.assertTrue(model['layer2']['mac_learning']['dynamic_learning_present'])
        self.assertFalse(model['layer2']['lldp']['enabled'])
        self.assertFalse(model['security']['snooping_bindings']['has_bindings'])
        self.assertFalse(model['security']['device_tracking']['has_entries'])

    def test_regression_on_syslog_server_is_detected(self):
        modified=copy.deepcopy(self.post)
        modified['model']['system']['logging']['remote_servers']=[]
        report=compare_snapshots(self.pre,modified,self.rules,'17.5.6')
        self.assertEqual(report['sections']['system']['status'],'CHANGE')
        self.assertTrue(any('remote_servers' in c['path'] for c in report['sections']['system']['changes']))

    def test_regression_on_optic_missing_is_detected(self):
        modified=copy.deepcopy(self.post)
        modified['model']['hardware']['transceivers']['TenGigabitEthernet1/1/1']['present']=False
        report=compare_snapshots(self.pre,modified,self.rules,'17.5.6')
        self.assertEqual(report['sections']['hardware']['status'],'CHANGE')

    def test_cpu_threshold_crossing(self):
        modified=copy.deepcopy(self.post)
        modified['model']['hardware']['cpu_health']['cpu_high_5min']=True
        report=compare_snapshots(self.pre,modified,self.rules,'17.5.6')
        self.assertEqual(report['sections']['hardware']['status'],'CHANGE')

    def test_raw_normalizer_rejects_garbage(self):
        for command in ('show clock','show module','show processes cpu sorted','show logging'):
            fn=NORMALIZERS[command][2]
            with self.subTest(command=command),self.assertRaises(ValueError):
                fn('nonsensical output without data',None)

    def test_changed_syslog_event_lines_do_not_change_semantic_model(self):
        pre=PRE.read_text(encoding='utf-8')
        post=pre.replace('Oct 28 13:42:51.300 CST:', 'Oct 28 15:42:51.300 CST:')
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'post.txt';f.write_text(post,encoding='utf-8')
            normalized=parse_capture(f)
        self.assertEqual(self.pre['model']['system']['logging'],normalized['model']['system']['logging'])

if __name__ == '__main__': unittest.main()
