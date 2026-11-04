"""Render console tree, JSON, compact text report, HTML and CSV."""
from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Iterable

COLORS={'PASS':'#13804a','EXPECTED':'#14816d','CHANGE':'#bd8300','ERROR':'#b42c37',
        'MISSING':'#b42c37','NOT_EVALUATED':'#667085','INCOMPLETE':'#bd8300'}


def write_json(path: Path,obj: dict)->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,indent=2,ensure_ascii=False,default=str)+'\n',encoding='utf-8')


def _value(x:object)->str:
    if isinstance(x,(dict,list)):return json.dumps(x,ensure_ascii=False,sort_keys=True,default=str)
    return str(x)


def write_report(folder:Path,report:dict)->None:
    folder.mkdir(parents=True,exist_ok=True)
    dev=report['device']
    write_json(folder/f'{dev}.json',report)
    lines=['CISCO SNAPSHOT SMART DIFF','='*82,
       f"Device   : {dev}",f"Compare  : Snapshot {report['snapshot_from']} -> {report['snapshot_to']}",
       f"Expected : {report['expected_version'] or 'Not specified'}",
       f"Engine   : {report['comparison_engine']}",'-'*82]
    for section,item in report['sections'].items():
        lines.append(f"[{item['status']:<14}] {section}")
        if item.get('reason'):lines.append('    '+item['reason'])
        for ch in item['changes']:
            lines.append(f"    {ch['path']}\n      FROM: {_value(ch.get('old'))}\n      TO  : {_value(ch.get('new'))}")
    lines+=['-'*82,'COMMAND COVERAGE']
    for cmd,c in report['commands'].items():
        if c['status']!='NORMALIZED':
            lines.append(f"  {cmd}: {c['first']} -> {c['second']}")
    lines+=['-'*82,f"RESULT: {report['overall_status']}",report['note']]
    (folder/f'{dev}.diff').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    from .html_report import make_html_report
    page=make_html_report(report)
    (folder/f'{dev}.html').write_text(page,encoding='utf-8')


def write_summary(folder:Path,reports:Iterable[dict])->None:
    with (folder/'summary.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f)
        writer.writerow(['Device','From','To','Result','Pass Sections','Changed Sections','Incomplete Sections'])
        for r in reports:
            s=[x['status'] for x in r['sections'].values()]
            writer.writerow([r['device'],r['snapshot_from'],r['snapshot_to'],r['overall_status'],
                s.count('PASS')+s.count('EXPECTED'),sum(x in ('CHANGE','ERROR','MISSING') for x in s),
                sum(x in ('NOT_EVALUATED','MISSING') for x in s)])


def console_tree(report:dict)->None:
    try:
        from rich.console import Console
        from rich.tree import Tree
    except ImportError:
        print(f"{report['device']}: {report['overall_status']}")
        for name,r in report['sections'].items():print(' -',name,r['status'])
        return
    console=Console()
    root=Tree(f"{report['device']}  [{report['overall_status']}]")
    color={'PASS':'green','EXPECTED':'green','CHANGE':'yellow','ERROR':'red','MISSING':'red'}
    for name,item in report['sections'].items():
        status=item['status']
        branch=root.add(f'[{color.get(status,"dim")}]' +status+f'[/]  {name}')
        for c in item['changes'][:30]:
            # escape Rich markup from arbitrary values and paths
            from rich.markup import escape
            branch.add(escape(f"{c['path']}: {_value(c.get('old'))} -> {_value(c.get('new'))}"))
        if len(item['changes'])>30:branch.add(f"... {len(item['changes'])-30} additional changes (see report)")
    console.print(root)
