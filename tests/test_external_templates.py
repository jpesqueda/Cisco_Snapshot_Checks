"""External template integration tests (can run even without textfsm installed)."""
from __future__ import annotations

import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from snapshotchecks.parsing import (
    candidate_template_names, find_custom_template, parse_capture,
    resolve_templates_dir, textfsm_parse,
)
from snapshotchecks.storage import command_block, content_header


class FakeTextFSM:
    """Small transport double: verifies integration, not TextFSM regex behavior."""
    def __init__(self, stream):
        if 'Value' not in stream.read():
            raise ValueError('Invalid template')
        self.header = ['PORT', 'FCS']

    def ParseText(self, body):
        return [['Gi1/0/1', '0']] if 'Gi1/0/1' in body else []


class ExternalTemplateTests(unittest.TestCase):
    def test_exact_file_name_and_no_prefix_matches(self):
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp)
            (d/'cisco_ios_show_switch_detail.textfsm').write_text('Value X (.*)\n')
            self.assertIsNone(find_custom_template('show switch','cisco_ios',d))
            self.assertIsNotNone(find_custom_template('show switch detail','cisco_ios',d))
            self.assertIn('cisco_ios_show_interface_link.textfsm',
                          candidate_template_names('show interfaces link','cisco_ios'))

    def test_custom_folder_auto_lookup_errors_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(resolve_templates_dir(tmp), Path(tmp).resolve())
        with self.assertRaises(ValueError):
            resolve_templates_dir('X:/this_directory_should_not_exist_/external_ntc')

    def test_template_parses_and_normalizes_known_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp)
            (d/'cisco_ios_show_interfaces_counters_errors.textfsm').write_text('Value PORT (\\S+)\n')
            fake=types.SimpleNamespace(TextFSM=FakeTextFSM)
            with patch.dict('sys.modules',{'textfsm':fake,'ntc_templates':None,'ntc_templates.parse':None}):
                result=textfsm_parse('show interfaces counters errors','Gi1/0/1 0 0 0 0 0 0',
                                     'cisco_ios',d)
            self.assertEqual(result.parser,'custom_textfsm')
            self.assertEqual(result.rows[0]['port'],'Gi1/0/1')

    def test_parsed_unmapped_is_not_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp)
            templates=d/'ntc_templates_cisco_ios'; templates.mkdir()
            (templates/'cisco_ios_show_unregistered_test.textfsm').write_text('Value PORT (\\S+)\n')
            raw=d/'switch.txt'
            raw.write_text(content_header('SW01','SW01','001') + command_block('show unregistered test','Gi1/0/1 0'),
                           encoding='utf-8')
            fake=types.SimpleNamespace(TextFSM=FakeTextFSM)
            with patch.dict('sys.modules',{'textfsm':fake,'ntc_templates':None,'ntc_templates.parse':None}):
                parsed=parse_capture(raw,templates_dir=templates)
            entry=parsed['coverage']['show unregistered test']
            self.assertEqual(entry['status'],'PARSED_UNMAPPED')
            self.assertEqual(entry['parser'],'custom_textfsm')
            self.assertNotIn('clock',parsed['model'])

    def test_invalid_template_recorded_not_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp)
            (d/'cisco_ios_show_clock.textfsm').write_text('broken')
            raw=d/'switch.txt'
            raw.write_text(content_header('SW01','SW01','001') + command_block('show clock','10:00:00'),
                           encoding='utf-8')
            fake=types.SimpleNamespace(TextFSM=FakeTextFSM)
            with patch.dict('sys.modules',{'textfsm':fake,'ntc_templates':None,'ntc_templates.parse':None}):
                parsed=parse_capture(raw,templates_dir=d)
            entry=parsed['coverage']['show clock']
            self.assertEqual(entry['status'],'PARSE_ERROR')
            self.assertEqual(entry['template'],'cisco_ios_show_clock.textfsm')


if __name__=='__main__': unittest.main()
