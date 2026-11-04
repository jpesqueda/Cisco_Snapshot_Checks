"""Read-only SSH command collection, with concurrency and optional backups."""
from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor,as_completed
from dataclasses import dataclass,field
from datetime import datetime
from getpass import getpass
from pathlib import Path

from .storage import content_header,command_block,store_capture,safe_name

@dataclass
class Result:
    host:str
    success:bool=False
    reason:str=''
    commands_failed:list[str]=field(default_factory=list)


def capture_one(host:str,commands:list[str],username:str,password:str,
               root:Path,snap:str,platform:str,backup:bool)->Result:
    result=Result(host)
    conn=None
    try:
        try:
            from netmiko import ConnectHandler
        except ImportError as exc:
            raise RuntimeError('Netmiko is not installed. Run python -m pip install -r requirements.txt') from exc
        conn=ConnectHandler(device_type='cisco_xe',host=host,username=username,password=password,
                            conn_timeout=20,auth_timeout=30,banner_timeout=30,fast_cli=False)
        name=conn.find_prompt().strip().rstrip('#>').split('(',1)[0].strip() or host
        records={}
        for cmd in commands:
            try:
                output=str(conn.send_command(cmd,read_timeout=120,strip_command=True,strip_prompt=True))
                records[cmd]=output
                if re.search(r'(?im)^\s*%\s*(?:Invalid input|Incomplete command|Ambiguous command|Authorization failed)',output):
                    result.commands_failed.append(cmd+' (CLI error)')
            except Exception as exc:
                records[cmd]=f'[COMMAND ERROR] {type(exc).__name__}: {str(exc).splitlines()[0][:180]}'
                result.commands_failed.append(cmd+' ('+type(exc).__name__+')')
        backup_content=None
        if backup:
            try:
                config=records.get('show running-config')
                if config is None:
                    config=str(conn.send_command('show running-config',read_timeout=180,
                        strip_command=True,strip_prompt=True))
                if not config.strip() or re.search(r'(?im)^\s*%\s*(Invalid input|Authorization failed)',config):
                    raise ValueError('Empty/invalid running-config')
                backup_content=(content_header(host,name,snap)+config.rstrip()+'\n')
            except Exception as exc:
                result.commands_failed.append('show running-config backup ('+type(exc).__name__+')')
        full=content_header(host,name,snap)+''.join(command_block(c,records[c]) for c in commands)
        store_capture(root,snap,host,full,platform,backup=backup_content)
        result.success=not result.commands_failed
        result.reason='Completed' if result.success else f'{len(result.commands_failed)} command/backup failure(s)'
    except Exception as exc:
        result.reason=type(exc).__name__+': '+str(exc).splitlines()[0][:180]
    finally:
        if conn is not None:
            try:conn.disconnect()
            except Exception:pass
    return result


def collect_all(hosts:list[str],commands:list[str],username:str,password:str,
                root:Path,snap:str,platform:str,backup:bool,workers:int)->list[Result]:
    try:
        from rich.console import Console
        from rich.progress import Progress,BarColumn,TaskProgressColumn,TextColumn
        console=Console()
        progress=Progress(TextColumn('Cisco IOS-XE checks'),BarColumn(bar_width=40),
                          TaskProgressColumn(),TextColumn('{task.completed}/{task.total}'),console=console)
    except ImportError:
        progress=None
    logger=logging.getLogger(f'network_snapshot.{time.monotonic_ns()}')
    logger.setLevel(logging.INFO)
    logger.propagate=False
    folder=root/'Logs';folder.mkdir(parents=True,exist_ok=True)
    logfile=folder/f'SNAPSHOT_{snap}_{datetime.now().strftime("%Y%m%d_%H%M%S_%f")}.log'
    handler=logging.FileHandler(logfile,encoding='utf-8');logger.addHandler(handler)
    results=[]
    try:
        import contextlib
        with progress if progress else contextlib.nullcontext():
            task=progress.add_task('checks',total=len(hosts)) if progress else None
            with ThreadPoolExecutor(max_workers=min(workers,len(hosts))) as pool:
                futures={pool.submit(capture_one,h,commands,username,password,root,snap,platform,backup):h for h in hosts}
                for idx,f in enumerate(as_completed(futures),1):
                    r=f.result()
                    results.append(r)
                    logger.info('[%d/%d] %s: %s (%s)',idx,len(hosts),r.host,'Success' if r.success else 'Failed',r.reason)
                    for e in r.commands_failed:logger.info('    COMMAND FAILURE: %s',e)
                    if progress:progress.advance(task)
                    else:print(f'Completed {idx}/{len(hosts)}')
    finally:
        handler.close();logger.removeHandler(handler)
    return results
