"""Snapshot numbering, collision checks, atomic file writes, and imports."""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path

from .parsing import parse_capture
from .reports import write_json


def default_root() -> Path:
    return Path(datetime.now().strftime('%d-%b-%Y').upper())


def safe_name(host: str) -> str:
    return re.sub(r'[^A-Za-z0-9_.-]','_',host).strip('._') or 'unnamed_device'


def snapshot_id(value:str)->str:
    if not value.isdigit() or int(value)<1 or len(value)>6:
        raise ValueError('Snapshot must be a positive number, e.g. 001 or 002')
    return f'{int(value):03d}'


def next_snapshot(root:Path)->str:
    base=root/'Snapshots'
    available=[int(p.name) for p in base.iterdir() if p.is_dir() and p.name.isdigit()] if base.is_dir() else []
    return f'{max(available,default=0)+1:03d}'


def atomic_text(path:Path,text:str)->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.parent/f'.{path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp'
    try:
        temp.write_text(text,encoding='utf-8',errors='replace')
        os.replace(temp,path)
    finally:
        temp.unlink(missing_ok=True)


def store_capture(root:Path,snap:str,host:str,content:str,platform:str,
                  backup:str|None=None)->tuple[Path,Path,dict]:
    base=root/'Snapshots'/snap
    name=safe_name(host)
    raw=base/'Checks'/f'{name}.txt'
    data=base/'JSON'/f'{name}.json'
    parsed=parse_capture_input(content,raw,platform,snap)
    parsed['metadata']['source']=raw.name
    # Atomic commit of TXT and JSON; root is not forcibly deleted.
    atomic_text(raw,content)
    write_json(data,parsed)
    if backup is not None:
        atomic_text(base/'Backups'/f'{name}_Running_Config.txt',backup)
    return raw,data,parsed


def parse_capture_input(content:str,path:Path,platform:str,snap:str)->dict:
    """Use a unique temporary file because extract_commands reads the same format as raw captures."""
    tmp=path.parent/f'.{path.name}.{os.getpid()}.{time.monotonic_ns()}.parse.tmp'
    tmp.parent.mkdir(parents=True,exist_ok=True)
    try:
        tmp.write_text(content,encoding='utf-8')
        return parse_capture(tmp,platform=platform,snapshot=snap)
    finally:
        tmp.unlink(missing_ok=True)


def import_existing(root:Path,snap:str,source:Path,platform:str)->tuple[Path,Path,dict]:
    text=source.read_text(encoding='utf-8-sig',errors='replace')
    # Parse once from source, then save under stable host identifier.
    parsed=parse_capture(source,platform=platform,snapshot=snap)
    host=parsed['metadata']['device']
    dest=root/'Snapshots'/snap/'Checks'/f'{safe_name(host)}.txt'
    if dest.resolve()==source.resolve():
        raise ValueError('Source is already the destination snapshot file')
    atomic_text(dest,text)
    data=root/'Snapshots'/snap/'JSON'/f'{safe_name(host)}.json'
    parsed['metadata']['source']=dest.name
    write_json(data,parsed)
    return dest,data,parsed


def read_snapshot(root:Path,snap:str)->dict[str,Path]:
    base=root/'Snapshots'/snap/'JSON'
    return {p.stem.casefold():p for p in base.glob('*.json')} if base.is_dir() else {}


def content_header(target:str,hostname:str,snap:str)->str:
    date=datetime.now().astimezone().isoformat(timespec='seconds')
    return ('='*70+'\nCISCO IOS-XE SNAPSHOT CHECKS\n'+'='*70+'\n'
            f'RUN_TIMESTAMP: {date}\nTARGET: {target}\nHOSTNAME: {hostname}\nSNAPSHOT: {snap}\n'+'='*70+'\n\n')


def command_block(cmd:str,raw:str)->str:
    sep='#'*70
    return f'{sep}\nCOMMAND: {cmd}\n{sep}\n\n{raw.rstrip()}\n\n'
