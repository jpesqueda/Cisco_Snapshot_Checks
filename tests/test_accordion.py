"""Semantic field rows and secure interactive HTML render tests."""
from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from snapshotchecks.comparison import compare_snapshots, load_rules
from snapshotchecks.parsing import parse_capture
from snapshotchecks.reports import write_report

HERE = Path(__file__).resolve().parents[1]


class AccordionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pre = parse_capture(HERE / 'examples' / 'C9300-ACCESS-01_PRE_SIMULATED.txt',snapshot='001')
        cls.post = parse_capture(HERE / 'examples' / 'C9300-ACCESS-01_POST_SIMULATED.txt',snapshot='002')
        cls.rules = load_rules(HERE / 'compare_rules.yaml')

    def test_compared_rows_have_all_four_fields(self):
        report = compare_snapshots(self.pre,self.post,self.rules,'17.5.6')
        rows = report['sections']['interfaces']['rows']
        self.assertGreater(len(rows), 100)
        self.assertTrue(all({'field','old','new','status'} <= row.keys() for row in rows))
        self.assertTrue(all(row['status']=='PASS' for row in rows))
        version = next(r for r in report['sections']['system']['rows'] if r['field'] == 'os_version')
        self.assertEqual((version['old'],version['new'],version['status']),('17.5.5','17.5.6','EXPECTED'))
        self.assertEqual(report['overall_status'],'INCOMPLETE')

    def test_changes_only_has_actual_different_rows(self):
        modified=copy.deepcopy(self.post)
        modified['model']['vlans']['20']['status']='suspended'
        modified['model']['interfaces']['GigabitEthernet1/0/15']['oper_status']='notconnect'
        modified['model']['routing']['bgp']['neighbors']['10.255.0.1']['state']='Idle'
        result=compare_snapshots(self.pre,modified,self.rules,'17.5.6')
        self.assertEqual(result['overall_status'],'CHANGE')
        for section in ('vlans','interfaces','routing'):
            self.assertIn('CHANGE', {r['status'] for r in result['sections'][section]['rows']})

    def test_html_expands_and_filters_and_escapes(self):
        changed=copy.deepcopy(self.post)
        changed['model']['interfaces']['GigabitEthernet1/0/15']['description'] = '<script>alert(1)</script>'
        result=compare_snapshots(self.pre,changed,self.rules,'17.5.6')
        with tempfile.TemporaryDirectory() as work:
            write_report(Path(work),result)
            html = (Path(work)/'C9300-ACCESS-01.html').read_text(encoding='utf-8')
            self.assertIn('FIELD</th><th>PRE</th><th>POST</th><th>STATUS',html)
            self.assertIn('id="expand"',html)
            self.assertIn('id="collapse"',html)
            self.assertIn('id="changes-only"',html)
            self.assertIn('id="search"',html)
            self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;',html)
            self.assertNotIn('<script>alert(1)</script>',html)
            self.assertNotIn('REPLACE_ME_TACACS_SHARED_KEY',html)

    def test_expected_version_error_on_row(self):
        result = compare_snapshots(self.pre,self.post,self.rules,'17.5.7')
        self.assertEqual(next(r for r in result['sections']['system']['rows'] if r['field']=='os_version')['status'],'ERROR')


if __name__ == '__main__':
    unittest.main()
