"""Run with: python -m unittest discover -s tests -v"""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from snapshotchecks.parsing import parse_capture,extract_commands
from snapshotchecks.comparison import load_rules,compare_snapshots
from snapshotchecks.reports import write_report
from snapshotchecks.storage import import_existing,read_snapshot,next_snapshot

HERE=Path(__file__).resolve().parents[1]
PRE=HERE/'examples'/'C9300-ACCESS-01_PRE_SIMULATED.txt'
POST=HERE/'examples'/'C9300-ACCESS-01_POST_SIMULATED.txt'


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pre=parse_capture(PRE,snapshot='001')
        cls.post=parse_capture(POST,snapshot='002')
        cls.rules=load_rules(HERE/'compare_rules.yaml')

    def test_43_commands_and_version(self):
        self.assertEqual(self.pre['metadata']['command_count'],43)
        self.assertEqual(self.post['metadata']['command_count'],43)
        self.assertEqual(self.pre['model']['system']['os_version'],'17.5.5')
        self.assertEqual(self.post['model']['system']['os_version'],'17.5.6')
        self.assertEqual(self.pre['model']['routing']['bgp']['neighbors']['10.255.0.1']['state'],'Established')
        self.assertIn('GigabitEthernet1/0/48',self.pre['model']['interfaces'])

    def test_not_text_diff_on_ordinary_reboot(self):
        r=compare_snapshots(self.pre,self.post,self.rules,'17.5.6')
        self.assertEqual(r['sections']['system']['status'],'EXPECTED')
        for k in ['hardware','interfaces','vlans','routing','layer2','security']:
            self.assertEqual(r['sections'][k]['status'],'PASS',k)
        self.assertEqual(r['overall_status'],'INCOMPLETE')  # Unsupported commands exist.

    def test_detects_real_regressions(self):
        broken=copy.deepcopy(self.post)
        broken['model']['vlans']['20']['status']='suspended'
        broken['model']['routing']['bgp']['neighbors']['10.255.0.1']['state']='Idle'
        broken['model']['interfaces']['GigabitEthernet1/0/1']['oper_status']='err-disabled'
        r=compare_snapshots(self.pre,broken,self.rules,'17.5.6')
        self.assertEqual(r['overall_status'],'CHANGE')
        for section in ['interfaces','vlans','routing']:
            self.assertEqual(r['sections'][section]['status'],'CHANGE',section)

    def test_expected_version_mismatch(self):
        r=compare_snapshots(self.pre,self.post,self.rules,'17.5.7')
        self.assertEqual(r['sections']['system']['status'],'ERROR')

    def test_missing_command_is_not_pass(self):
        post=copy.deepcopy(self.post)
        del post['coverage']['show vlan brief']
        r=compare_snapshots(self.pre,post,self.rules)
        self.assertEqual(r['commands']['show vlan brief']['status'],'MISSING')
        self.assertNotEqual(r['overall_status'],'PASS')

    def test_sensitive_running_config_not_copied_to_json(self):
        self.assertEqual(self.pre['coverage']['show running-config']['status'],'SKIPPED_SENSITIVE')
        s=json.dumps(self.pre['model'])
        self.assertNotIn('REPLACE_ME_TACACS_SHARED_KEY',s)
        self.assertNotIn('service password-encryption',s)

    def test_raw_txt_regression_pipeline(self):
        raw=POST.read_text(encoding='utf-8')
        raw=raw.replace('20   USERS                            active',
                        '20   USERS                            suspended',1)
        raw=raw.replace('2w1d     1','2w1d     Idle',1) if '2w1d     1' in raw else raw
        # POST already has 10-minute BGP uptime; target only its table row.
        raw=__import__('re').sub(r'(?m)^(10\.255\.0\.1\s+4\s+65000\s+[^\n]*?)\s+1\s*$',
                         r'\1 Idle',raw,count=1)
        raw=raw.replace('Gi1/0/1    USER_01              connected',
                        'Gi1/0/1    USER_01              err-disabled',1)
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'POST_MODIFIED.txt'
            p.write_text(raw,encoding='utf-8')
            after=parse_capture(p,snapshot='002')
            report=compare_snapshots(self.pre,after,self.rules,'17.5.6')
            self.assertEqual(report['sections']['vlans']['status'],'CHANGE')
            self.assertEqual(report['sections']['interfaces']['status'],'CHANGE')
            self.assertEqual(report['sections']['routing']['status'],'CHANGE')

    def test_write_html_and_diff(self):
        with tempfile.TemporaryDirectory() as td:
            r=compare_snapshots(self.pre,self.post,self.rules,'17.5.6')
            write_report(Path(td),r)
            self.assertIn('<details', (Path(td)/'C9300-ACCESS-01.html').read_text())
            self.assertIn('EXPECTED', (Path(td)/'C9300-ACCESS-01.diff').read_text())

    def test_import_and_numbering(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            self.assertEqual(next_snapshot(root),'001')
            import_existing(root,'001',PRE,'cisco_ios')
            import_existing(root,'002',POST,'cisco_ios')
            self.assertEqual(next_snapshot(root),'003')
            self.assertEqual(len(read_snapshot(root,'001')),1)
            self.assertEqual(len(read_snapshot(root,'002')),1)


if __name__=='__main__':unittest.main()
