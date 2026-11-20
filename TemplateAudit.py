#!/usr/bin/env python3
"""Read-only static/runtime audit of external Cisco TextFSM templates.

Windows: python TemplateAudit.py -cf cmd.txt --templates-dir ntc_templates_cisco_ios
         python TemplateAudit.py -cf cmd.txt --capture examples/SW01_PRE.txt -o Template_Audit
No SSH calls, no device configuration changes. Static matches are candidates,
NOT evidence that any template successfully parses real device output.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from snapshotchecks.parsing import (
    NORMALIZERS, canonical_command, extract_commands, find_custom_template,
    index_match, parse_capture, resolve_templates_dir,
)


def main() -> int:
    parser=argparse.ArgumentParser(description='Audit TextFSM templates against Cisco command list and optional capture.',
                                    formatter_class=argparse.RawDescriptionHelpFormatter,
                                    epilog='EXAMPLES:\n  python TemplateAudit.py -cf cmd.txt\n  python TemplateAudit.py -cf cmd.txt --capture examples/C9300-ACCESS-01_PRE_SIMULATED.txt -o Audit_Results')
    parser.add_argument('-cf','--cmd',default='cmd.txt',help='Commands file (default cmd.txt)')
    parser.add_argument('--capture',help='Optional PRE/POST check TXT to test runtime parsing')
    parser.add_argument('--templates-dir',help='Directory with .textfsm files and index')
    parser.add_argument('-o','--output',default='Template_Audit',help='Directory for CSV/JSON audit files')
    args=parser.parse_args()
    source=Path(args.cmd).expanduser()
    if not source.is_file():parser.error('Commands file not found: '+str(source))
    cmd_list=list(dict.fromkeys(canonical_command(x) for x in source.read_text(encoding='utf-8-sig').splitlines()
                       if x.strip() and not x.lstrip().startswith('#')))
    directory=resolve_templates_dir(args.templates_dir)
    if directory is None:parser.error('Template directory not found; use --templates-dir')
    capture_data=None
    if args.capture:
        path=Path(args.capture).expanduser()
        if not path.is_file():parser.error('Capture not found: '+str(path))
        capture_data=parse_capture(path,templates_dir=directory)
    rows=[]
    for command in cmd_list:
        indexed=index_match(command,'cisco_ios',directory)
        file=find_custom_template(command,'cisco_ios',directory)
        candidate=indexed or (file.name if file else '')
        coverage=(capture_data or {}).get('coverage',{}).get(command, {})
        rows.append({'command':command,
                     'custom_template':candidate,
                     'template_candidate':'YES' if candidate else 'NO',
                     'normalizer':'YES' if command in NORMALIZERS else 'NO',
                     'runtime_status':coverage.get('status','NOT_TESTED'),
                     'runtime_parser':coverage.get('parser',''),
                     'runtime_records':coverage.get('records',''),
                     'runtime_error':coverage.get('error','')})
    output=Path(args.output).expanduser();output.mkdir(parents=True,exist_ok=True)
    with (output/'template_coverage.csv').open('w',newline='',encoding='utf-8-sig') as file:
        writer=csv.DictWriter(file,fieldnames=list(rows[0]) if rows else ['command'])
        writer.writeheader();writer.writerows(rows)
    (output/'template_coverage.json').write_text(json.dumps({'templates_dir':str(directory),
                           'capture':args.capture,'commands':rows},indent=2,ensure_ascii=False),encoding='utf-8')
    stats=Counter(x['runtime_status'] for x in rows)
    candidates=sum(r['template_candidate']=='YES' for r in rows)
    print('Commands: ',len(rows))
    print('Custom template candidates: ',candidates)
    print('With normalized comparison rules: ',sum(r['normalizer']=='YES' for r in rows))
    if args.capture:print('Runtime status: ',dict(stats))
    else:print('Parsing was not tested. Templates are name/index candidates only.')
    print('CSV: ',output/'template_coverage.csv')
    print('JSON:',output/'template_coverage.json')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
