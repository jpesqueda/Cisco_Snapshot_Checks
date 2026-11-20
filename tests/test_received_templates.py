"""Structural tests of the received TextFSM directory; no TextFSM installation required."""
from pathlib import Path
import unittest
from unittest.mock import patch
from snapshotchecks.parsing import (index_match,find_custom_template,parse_capture,
                                    _index_regex, textfsm_parse)

TEMPLATES=Path(__file__).resolve().parent.parent/'ntc_templates_cisco_ios'

class UserTemplateTests(unittest.TestCase):
    def test_33_real_textfsm_files(self):
        self.assertEqual(len(list(TEMPLATES.glob('*.textfsm'))),33)
    def test_multi_file_index(self):
        self.assertIn(':',index_match('show switch','cisco_ios',TEMPLATES))
        self.assertIn(':',index_match('show module','cisco_ios',TEMPLATES))
    def test_no_wrong_interface_template(self):
        self.assertIsNone(index_match('show interfaces counters errors','cisco_ios',TEMPLATES))
        self.assertIsNone(index_match('show interface status','cisco_ios',TEMPLATES))
    def test_exact_dash_files(self):
        self.assertIn('mac-address-table',find_custom_template('show mac address-table','cisco_ios',TEMPLATES).name)
        self.assertIn('device-tracking',find_custom_template('show device-tracking database','cisco_ios',TEMPLATES).name)
    def test_cpu_sorted_alias_file(self):
        self.assertTrue(find_custom_template('show processes cpu sorted','cisco_ios',TEMPLATES).is_file())
    def test_builtin_normalization_with_real_captures(self):
        source=Path(__file__).resolve().parent.parent/'examples'/'C9300-ACCESS-01_PRE_SIMULATED.txt'
        record=parse_capture(source,templates_dir=TEMPLATES)
        self.assertEqual(len(record['coverage']),43)
        for cmd in ('show inventory','show switch','show interfaces','show interfaces switchport',
                    'show power inline','show ip arp inspection interfaces','show ip dhcp snooping'):
            self.assertEqual(record['coverage'][cmd]['status'],'NORMALIZED',cmd)
        self.assertEqual(record['coverage']['show running-config']['status'],'SKIPPED_SENSITIVE')

if __name__=='__main__':unittest.main()
