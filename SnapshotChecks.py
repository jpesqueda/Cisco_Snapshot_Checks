#!/usr/bin/env python3
"""Cisco Snapshot Checks: collect/import/compare any numbered snapshots.

Use --help for complete examples. -h is intentionally reserved for --host.
Requires Python 3.10+. See README.md for limitations and security notes.
"""
from __future__ import annotations

import argparse
import json
import sys
from getpass import getpass
from pathlib import Path

from snapshotchecks.collect import collect_all
from snapshotchecks.comparison import compare_snapshots,load_rules
from snapshotchecks.parsing import parse_capture
from snapshotchecks.reports import console_tree,write_report,write_summary
from snapshotchecks.storage import (default_root,import_existing,next_snapshot,read_snapshot,
                                    safe_name,snapshot_id)

BANNER='CISCO NETWORK SNAPSHOT CHECKS'
EXAMPLES='''EXAMPLES:
  Interactive collection:
    python SnapshotChecks.py

  Collect snapshot 001 using a host file:
    python SnapshotChecks.py collect -hf hosts.txt -cf cmd.txt -u admin --snapshot 001 -b

  Collect snapshot 002 after an upgrade:
    python SnapshotChecks.py collect -hf hosts.txt -cf cmd.txt -u admin --snapshot 002 -b

  Automatically assign the next snapshot ID:
    python SnapshotChecks.py collect -h SW01 -u admin -o Upgrade_Cat9k

  Import existing legacy PRE/POST TXT files (no SSH):
    python SnapshotChecks.py import -f C9300-ACCESS-01_PRE_SIMULATED.txt --snapshot 001 -o Lab
    python SnapshotChecks.py import -f C9300-ACCESS-01_POST_SIMULATED.txt --snapshot 002 -o Lab

  Compare snapshots 001 and 002 (no SSH):
    python SnapshotChecks.py compare --from 001 --to 002 -o Lab --expected-version 17.5.6 --tree

  Open collapsible comparison tables in PowerShell:
    python SnapshotChecks.py compare --from 001 --to 002 -o Lab --tui

  Compare just one switch:
    python SnapshotChecks.py compare --from 001 --to 003 -o Lab -h SW01

NOTES:
  -h = --host. Use --help to display this page.
  Default output directory: DD-MMM-YYYY.
  Missing collect arguments are prompted interactively.
  Compare only evaluates mapped fields; unknown commands are NOT reported PASS.
'''


def _common(parser:argparse.ArgumentParser):
    parser.add_argument('-o','--output',metavar='DIR',help='Project root (default: current date)')
    parser.add_argument('--platform',default='cisco_ios',metavar='NAME',
                        help='NTC Templates platform (default: cisco_ios)')
    parser.add_argument('--help',action='help',help='Show help for this action')


def argument_parser() -> argparse.ArgumentParser:
    main=argparse.ArgumentParser(prog='SnapshotChecks.py',add_help=False,
       formatter_class=argparse.RawDescriptionHelpFormatter,
       description='Network snapshots and semantic comparisons (no configuration changes).',
       epilog=EXAMPLES)
    main.add_argument('--help',action='help',help='Show help and examples')
    actions=main.add_subparsers(dest='action',metavar='{collect,import,compare}')
    collect=actions.add_parser('collect',add_help=False,help='Collect a numbered snapshot over SSH')
    _common(collect)
    group=collect.add_mutually_exclusive_group()
    group.add_argument('-h','--host',metavar='HOST',help='One target device')
    group.add_argument('-hf','--host_file',metavar='FILE',help='File with target devices')
    collect.add_argument('-cf','--cmd',metavar='FILE',help='Commands file (default: cmd.txt)')
    collect.add_argument('-u','--username',metavar='USER',help='SSH username')
    collect.add_argument('-p','--password',metavar='PASS',help='SSH password (prefer secure prompt)')
    collect.add_argument('-b','--backup',action='store_true',help='Save running-config in Backups/')
    collect.add_argument('-w','--workers',type=int,default=20,metavar='N',help='Parallel SSH workers (default 20)')
    collect.add_argument('--snapshot','--id',default=None,metavar='ID',help='Snapshot ID (default auto-increment)')
    imported=actions.add_parser('import',add_help=False,help='Import and normalize a legacy check TXT')
    _common(imported)
    imported.add_argument('-f','--file',required=True,metavar='TXT',help='Legacy PRE/POST TXT capture')
    imported.add_argument('--snapshot','--id',required=True,metavar='ID',help='Target snapshot number')
    compared=actions.add_parser('compare',add_help=False,help='Compare two existing snapshots offline')
    compared.add_argument('-o','--output',metavar='DIR',help='Project root (default: current date)')
    compared.add_argument('--help',action='help',help='Show help')
    compared.add_argument('--from',dest='source_id',required=True,metavar='ID',help='First snapshot')
    compared.add_argument('--to',dest='target_id',required=True,metavar='ID',help='Second snapshot')
    compared.add_argument('-h','--host',metavar='HOST',help='Only compare this device')
    compared.add_argument('--expected-version',metavar='VERSION',help='Expected IOS-XE version in second snapshot')
    compared.add_argument('--rules',metavar='YAML',help='Comparison policy (default: bundled compare_rules.yaml)')
    compared.add_argument('--tree',action='store_true',help='Print changed branches using Rich Tree')
    compared.add_argument('--tui',action='store_true',help='Open interactive Textual expandable tables')
    return main


def ask(label:str,default:str|None=None)->str:
    while True:
        val=input(f'{label}'+(f' [{default}]' if default else '')+': ').strip().strip('"').strip("'")
        if val:return val
        if default:return default
        print('A value is required.')


def confirm(message:str)->bool:
    while True:
        x=input(message+' (Y/N): ').strip().lower()
        if x in ('y','yes','s','si','sí'):return True
        if x in ('n','no'):return False
        print('Answer Y or N.')


def read_items(path:Path)->list[str]:
    if not path.is_file():raise FileNotFoundError(path)
    return [x.strip() for x in path.read_text(encoding='utf-8-sig').splitlines()
            if x.strip() and not x.lstrip().startswith('#')]


def handle_collect(args:argparse.Namespace)->int:
    root=Path(args.output).expanduser() if args.output else default_root()
    if args.host:hosts=[args.host]
    elif args.host_file:hosts=read_items(Path(args.host_file).expanduser())
    else:
        choice=ask('Host or Host File (host/file)').lower()
        if choice in ('host','h'):
            hosts=[ask('Host')]
        elif choice in ('file','f','host_file','hf'):
            hosts=read_items(Path(ask('Host File')).expanduser())
        else:
            cand=Path(choice)
            hosts=read_items(cand) if cand.is_file() else [choice]
    hosts=list(dict.fromkeys(hosts))
    if not hosts:raise ValueError('Host list is empty')
    if len({safe_name(h).casefold() for h in hosts})!=len(hosts):
        raise ValueError('Hostnames collide after filename sanitization')
    cmdpath=Path(args.cmd or ask('Commands File','cmd.txt')).expanduser()
    commands=list(dict.fromkeys(read_items(cmdpath)))
    if not commands:raise ValueError('Commands file is empty')
    if args.workers<1:raise ValueError('Workers must be positive')
    username=args.username or ask('Username')
    password=args.password if args.password is not None else getpass('Password: ')
    if not password:raise ValueError('Password cannot be blank')
    snap=snapshot_id(args.snapshot) if args.snapshot else next_snapshot(root)
    base=root/'Snapshots'/snap
    existing=list((base/'Checks').glob('*.txt')) if (base/'Checks').is_dir() else []
    if existing:
        print(f'[WARNING] Snapshot {snap} already has {len(existing)} device checks in {base}')
        if not confirm('Overwrite matching device outputs in this snapshot?'):
            print('Cancelled. Existing outputs preserved.')
            return 0
    print(f'\nSnapshot       : {snap}\nDevices        : {len(hosts)}\nCommands       : {len(commands)}\nOutput         : {root}')
    results=collect_all(hosts,commands,username,password,root,snap,args.platform,args.backup,args.workers)
    ok=sum(r.success for r in results)
    print(f'\nCollection Completed\nDevices Processed : {len(results)}\nSuccessful        : {ok}\nFailed            : {len(results)-ok}')
    print(f'Results : {base / "Checks"}\nJSON    : {base / "JSON"}\nLogs    : {root / "Logs"}')
    if args.backup:print(f'Backups : {base / "Backups"}')
    return 1 if ok!=len(results) else 0


def handle_import(args:argparse.Namespace)->int:
    root=Path(args.output).expanduser() if args.output else default_root()
    snap=snapshot_id(args.snapshot)
    source=Path(args.file).expanduser()
    if not source.is_file():raise FileNotFoundError(source)
    parsed=parse_capture(source,platform=args.platform,snapshot=snap)
    name=safe_name(parsed['metadata']['device'])
    destination=root/'Snapshots'/snap/'Checks'/f'{name}.txt'
    if destination.exists():
        print('[WARNING] Existing file: '+str(destination))
        if not confirm('Overwrite this snapshot file?'):return 0
    raw,jsonpath,parsed=import_existing(root,snap,source,args.platform)
    statuses={}
    for x in parsed['coverage'].values():statuses[x['status']]=statuses.get(x['status'],0)+1
    print(f'Imported : {raw}\nParsed   : {jsonpath}\nDevice   : {parsed["metadata"]["device"]}')
    print('Coverage : '+', '.join(f'{k}={v}' for k,v in statuses.items()))
    return 0


def handle_compare(args:argparse.Namespace)->int:
    root=Path(args.output).expanduser() if args.output else default_root()
    first=snapshot_id(args.source_id);second=snapshot_id(args.target_id)
    if first==second:raise ValueError('Snapshot IDs must be different')
    sources=read_snapshot(root,first)
    targets=read_snapshot(root,second)
    if not sources:raise FileNotFoundError(f'No JSON files in snapshot {first}; import/collect first')
    if not targets:raise FileNotFoundError(f'No JSON files in snapshot {second}; import/collect first')
    names=sorted({*sources,*targets})
    if args.host:
        name=safe_name(args.host).casefold()
        if name not in names:raise ValueError('Device not found in either snapshot: '+args.host)
        names=[name]
    policies=load_rules(Path(args.rules) if args.rules else Path(__file__).resolve().parent/'compare_rules.yaml')
    folder=root/'Reports'/f'{first}_vs_{second}'
    reports=[]
    missing=[]
    for name in names:
        if name not in sources or name not in targets:
            missing.append((name,first if name not in sources else second))
            continue
        a=json.loads(sources[name].read_text(encoding='utf-8'))
        b=json.loads(targets[name].read_text(encoding='utf-8'))
        if a['metadata']['device'].casefold()!=b['metadata']['device'].casefold():
            raise ValueError('Device identity mismatch across snapshots: '+name)
        report=compare_snapshots(a,b,policies,args.expected_version)
        write_report(folder,report)
        reports.append(report)
        print(f"{report['device']}  {report['overall_status']}")
        if args.tree:console_tree(report)
    write_summary(folder,reports)
    if missing:
        path=folder/'missing_devices.txt'
        path.write_text('\n'.join(f'{n}: not present in snapshot {snap}' for n,snap in missing)+'\n',encoding='utf-8')
        print(f'MISSING DEVICES: {len(missing)} (details: {path})')
    print(f'Reports : {folder}')
    if args.tui:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise RuntimeError('--tui needs an interactive terminal (PowerShell or Windows Terminal)')
        from snapshotchecks.tui import launch_tui
        launch_tui(reports)
    if any(r['overall_status']=='CHANGE' for r in reports) or missing:return 1
    if any(r['overall_status']=='INCOMPLETE' for r in reports):return 3
    return 0


def main()->int:
    parser=argument_parser()
    args=parser.parse_args()
    print('='*70+'\n'+BANNER.center(70)+'\n'+'='*70)
    if args.action is None:
        args=parser.parse_args(['collect'])
    if args.action=='collect':return handle_collect(args)
    if args.action=='import':return handle_import(args)
    if args.action=='compare':return handle_compare(args)
    parser.print_help();return 2


if __name__=='__main__':
    try:sys.exit(main())
    except (OSError,ValueError,RuntimeError) as exc:
        print(f'ERROR: {exc}',file=sys.stderr);sys.exit(2)
    except (KeyboardInterrupt,EOFError):
        print('\nInterrupted.');sys.exit(130)
