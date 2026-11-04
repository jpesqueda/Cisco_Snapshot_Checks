"""Parse command captures into a vendor-neutral, deliberately selective model.

Parsing order: NTC Templates/TextFSM -> a local, explicit fallback -> unsupported.
Parsing alone is NOT validation: a command must also have a registered normalizer.
No raw show running-config is copied into JSON or HTML reports.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

MARKER = re.compile(r'^#{15,}\s*\nCOMMAND:\s*(.+?)\s*\n#{15,}\s*$', re.M)
CLI_ERROR = re.compile(
    r'(?im)^\s*(?:\[COMMAND ERROR\]|%\s*(?:Invalid input|Incomplete command|'
    r'Ambiguous command|Error|Authorization failed|Permission denied)\b|Error opening\b)'
)
IFACE = re.compile(r'^(?:Gi|Te|Tw|Fo|Fa|Eth|Hu|Po|Vlan|Vl|Loopback|Lo|GigabitEthernet|TenGigabitEthernet|'
                   r'TwentyFiveGigE|FortyGigabitEthernet|HundredGigE|Port-channel)\d', re.I)


def canonical_command(name: str) -> str:
    value = ' '.join(name.strip().lower().split())
    aliases = {
        'show interfaces status': 'show interface status',
        'show interface statuses': 'show interface status',
        'show vlan': 'show vlan brief',
        'show ip bgp neighbors summary': 'show ip bgp summary',
    }
    return aliases.get(value, value)


def normalize_interface(value: str) -> str:
    value = str(value).strip()
    patterns = [('Gi','GigabitEthernet'), ('Te','TenGigabitEthernet'),
                ('Tw','TwentyFiveGigE'), ('Fo','FortyGigabitEthernet'),
                ('Fa','FastEthernet'), ('Po','Port-channel'), ('Vl','Vlan'),
                ('Lo','Loopback')]
    for short, long_name in patterns:
        if re.match(r'^'+short+r'\d', value, re.I):
            return long_name+value[len(short):]
    return value


def extract_commands(raw: str) -> dict[str, str]:
    """Extract from the PRE/POST collector's COMMAND markers, or new captures."""
    markers = list(MARKER.finditer(raw))
    if not markers:
        raise ValueError('No COMMAND: sections found in the TXT file')
    results: dict[str, str] = {}
    for idx, match in enumerate(markers):
        name = canonical_command(match.group(1))
        if name in results:
            raise ValueError('Duplicate command section: '+name)
        end = markers[idx+1].start() if idx+1 < len(markers) else len(raw)
        body = raw[match.end():end]
        results[name] = body.strip()
    return results



# External templates can be placed in this directory next to SnapshotChecks.py.
# An explicitly supplied --templates-dir always wins.
AUTO_TEMPLATE_DIRS = ('ntc_templates_cisco_ios', 'custom_ntc_templates')


def resolve_templates_dir(templates_dir: str | Path | None = None) -> Path | None:
    """Choose a trusted local template directory, without altering global NTC settings."""
    if templates_dir is not None:
        directory = Path(templates_dir).expanduser().resolve()
        if not directory.is_dir():
            raise ValueError(f'TextFSM template directory not found: {directory}')
        return directory
    project_dir = Path(__file__).resolve().parent.parent
    for name in AUTO_TEMPLATE_DIRS:
        candidate = project_dir / name
        if candidate.is_dir():
            return candidate.resolve()
    return None


def candidate_template_names(command: str, platform: str) -> tuple[str, ...]:
    """Match complete commands only: never match show switch to show switch detail."""
    command = canonical_command(command)
    names = [command]
    # These IOS-XE spellings mean the same command; no prefix/wildcard matching.
    interchangeable = {
        'show interface status': ['show interfaces status'],
        'show interfaces link': ['show interface link'],
        'show interface link': ['show interfaces link'],
        'show interfaces counters errors': ['show interface counters errors'],
        'show interfaces switchport': ['show interface switchport'],
        'show interfaces transceiver detail': ['show interface transceiver detail'],
    }
    names.extend(interchangeable.get(command, []))
    return tuple(dict.fromkeys(
        platform + '_' + re.sub(r'[^a-z0-9]+', '_', name).strip('_') + '.textfsm'
        for name in names
    ))


def find_custom_template(command: str, platform: str, directory: Path) -> Path | None:
    """Resolve YAML-mapped or convention-named templates with safe path checking."""
    index_yaml = directory / 'index.yaml'
    mapped = None
    if index_yaml.is_file():
        # YAML mapping is optional. An NTC-format 'index' is handled separately.
        try:
            import yaml
            mapping = yaml.safe_load(index_yaml.read_text(encoding='utf-8')) or {}
            mapped = mapping.get(platform, {}).get(canonical_command(command))
        except (ImportError, OSError, ValueError, TypeError, AttributeError):
            mapped = None
    filenames = ([mapped] if isinstance(mapped, str) else []) + list(candidate_template_names(command, platform))
    resolved = directory.resolve()
    for filename in filenames:
        candidate = (resolved / filename).resolve()
        if candidate.is_relative_to(resolved) and candidate.is_file() and candidate.suffix.lower()=='.textfsm':
            return candidate
    return None


@dataclass(frozen=True)
class TextFSMResult:
    rows: list[dict[str, Any]] | None = None
    parser: str | None = None
    template: str | None = None
    error: str | None = None


def _parse_template_file(template: Path, data: str, source: str) -> TextFSMResult:
    try:
        import textfsm
    except ImportError:
        return TextFSMResult(parser=source, template=template.name,
                             error='textfsm not installed; run python -m pip install -r requirements.txt')
    try:
        with template.open(encoding='utf-8-sig') as stream:
            table = textfsm.TextFSM(stream)
            parsed = table.ParseText(data)
        if not parsed:
            return TextFSMResult(parser=source, template=template.name,
                                 error='Template matched command name but did not match output')
        headers=[name.lower() for name in table.header]
        return TextFSMResult(rows=[dict(zip(headers,row)) for row in parsed],
                             parser=source,template=template.name)
    except Exception as exc:
        return TextFSMResult(parser=source,template=template.name,
                             error=f'{type(exc).__name__}: {str(exc)[:180]}')


def textfsm_parse(command: str, data: str, platform: str,
                  templates_dir: Path | None = None) -> TextFSMResult:
    """Try packaged NTC, user templates, then project-bundled templates.

    User templates support either a standard NTC 'index', an optional index.yaml
    command mapping or the canonical cisco_ios_show_....textfsm filename alone.
    NTC matching and template parsing are separate from semantic normalization.
    """
    try:
        from ntc_templates.parse import parse_output
    except ImportError:
        parse_output = None

    if parse_output is not None:
        try:
            parsed = parse_output(platform=platform, command=command, data=data)
            if isinstance(parsed,list) and parsed and isinstance(parsed[0],dict):
                return TextFSMResult(rows=parsed,parser='ntc_templates')
        except Exception:
            pass  # No packaged template; fall back to explicitly supplied templates.

    project_templates = Path(__file__).resolve().parent.parent / 'custom_templates'
    search_dirs = [p for p in (templates_dir, project_templates) if p is not None and p.is_dir()]
    first_error: TextFSMResult | None = None
    for directory in search_dirs:
        source='custom_textfsm' if directory != project_templates else 'bundled_textfsm'
        # Standard NTC cli-table index is supported when present in the user's directory.
        if (directory / 'index').is_file() and parse_output is not None:
            try:
                parsed = parse_output(platform=platform, command=command, data=data,
                                      template_dir=str(directory))
                if isinstance(parsed,list) and parsed and isinstance(parsed[0],dict):
                    return TextFSMResult(rows=parsed,parser=source+'_index')
            except Exception:
                pass
        template = find_custom_template(command,platform,directory)
        if template:
            result = _parse_template_file(template,data,source)
            if result.rows is not None:
                return result
            if first_error is None:
                first_error = result
    return first_error or TextFSMResult()


def _first(row: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        v = row.get(key)
        if v is not None and v != '':
            return v
    return default


def _int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return None


def version_parser(text: str, rows: list[dict] | None) -> dict:
    match = re.search(r'(?:Cisco IOS XE Software, Version|Catalyst L3 Switch Software[^\n]*?Version)\s+(\d+)\.(\d+)\.(\d+)',text,re.I)
    if not match and rows:
        v = str(_first(rows[0], 'version','os','software_version', default=''))
        match = re.search(r'(\d+)\.(\d+)\.(\d+)',v)
    if not match: raise ValueError('IOS-XE version not found')
    return {'os_version': '.'.join(str(int(x)) for x in match.groups())}


def status_parser(text: str, rows: list[dict] | None) -> dict:
    result={}
    if rows:
        for r in rows:
            name=_first(r, 'port','interface','intf')
            stat=_first(r, 'status','link_status')
            if name and stat:
                d={'oper_status':str(stat).strip().lower()}
                vlan=_first(r,'vlan','access_vlan')
                desc=_first(r,'name','description')
                if vlan is not None: d['access_vlan']=str(vlan)
                if desc is not None: d['description']=str(desc).strip()
                result[normalize_interface(name)]=d
    if not result:
        for line in text.splitlines():
            parts=line.split()
            if not parts or not IFACE.match(parts[0]): continue
            idx=next((i for i,p in enumerate(parts[1:],1) if p.lower() in
                     ('connected','notconnect','disabled','err-disabled','inactive','monitoring','suspended')),None)
            if idx and len(parts)>idx+1:
                result[normalize_interface(parts[0])]={'description':' '.join(parts[1:idx]),
                    'oper_status':parts[idx].lower(), 'access_vlan':parts[idx+1]}
    if not result: raise ValueError('No interface status rows found')
    return result


def brief_parser(text: str, rows: list[dict] | None) -> dict:
    result={}
    if rows:
        for r in rows:
            name=_first(r,'interface','intf')
            stat=_first(r,'status','admin_status')
            proto=_first(r,'protocol','protocol_status')
            if name and stat:
                d={'l3_status':str(stat).lower()}
                if proto is not None: d['protocol']=str(proto).lower()
                ip=_first(r,'ip_address','ipaddr','address')
                if ip is not None: d['ip_address']=str(ip)
                result[normalize_interface(name)]=d
    if not result:
        for line in text.splitlines():
            parts=line.split()
            if len(parts)<6 or not IFACE.match(parts[0]):continue
            result[normalize_interface(parts[0])]={'ip_address':parts[1],
                'l3_status':' '.join(parts[4:-1]).lower(),'protocol':parts[-1].lower()}
    if not result: raise ValueError('No IP interface brief rows found')
    return result


def description_parser(text: str, rows: list[dict] | None) -> dict:
    result={}
    if rows:
        for r in rows:
            name=_first(r,'port','interface')
            description=_first(r,'description','name')
            if name and description is not None: result[normalize_interface(name)]={'description':str(description)}
    if not result:
        for line in text.splitlines():
            parts=line.split(None,3)
            if len(parts)>=3 and IFACE.match(parts[0]) and parts[1].lower() in ('up','down','admin','disabled'):
                result[normalize_interface(parts[0])]={'description':parts[3] if len(parts)>3 else ''}
    if not result: raise ValueError('No interface descriptions found')
    return result


def vlans_parser(text: str, rows: list[dict] | None) -> dict:
    result={}
    if rows:
        for r in rows:
            vid=_first(r,'vlan_id','vlan','id')
            status=_first(r,'status','state')
            if vid is not None and status:
                result[str(vid)]={'name':str(_first(r,'name', default='')),'status':str(status).lower()}
    if not result:
        for line in text.splitlines():
            m=re.match(r'^\s*(\d{1,4})\s+(\S+)\s+(active|suspended|act/unsup)\b',line,re.I)
            if m: result[m.group(1)]={'name':m.group(2),'status':m.group(3).lower()}
    if not result: raise ValueError('No VLAN rows found')
    return result


def bgp_parser(text: str, rows: list[dict] | None) -> dict:
    match=re.search(r'local AS number\s+(\d+)',text,re.I)
    result={'neighbors':{}}
    if match: result['local_as']=int(match.group(1))
    if rows:
        for r in rows:
            peer=_first(r,'neighbor','neighbor_ip','peer','ip')
            if not peer:continue
            val=_first(r,'state_pfxrcd','state_prefix','state','state_pfxrcd','status',default='')
            prefix=_int(_first(r,'prefixes_received','pfxrcd'))
            if prefix is None: prefix=_int(val)
            state='Established' if prefix is not None else str(val)
            entry={'state':state}
            if prefix is not None:entry['prefixes_received']=prefix
            remote=_int(_first(r,'remote_as','as','asn'))
            if remote is not None:entry['remote_as']=remote
            result['neighbors'][str(peer)]=entry
    if not result['neighbors']:
        for line in text.splitlines():
            m=re.match(r'^\s*(\d{1,3}(?:\.\d{1,3}){3})\s+4\s+(\d+)\s+(.+)$',line)
            if not m:continue
            parts=m.group(3).split()
            if len(parts)<7:continue
            last=parts[-1]
            count=_int(last)
            entry={'remote_as':int(m.group(2)),'state':'Established' if count is not None else last}
            if count is not None:entry['prefixes_received']=count
            result['neighbors'][m.group(1)]=entry
    if not result['neighbors'] or 'local_as' not in result:
        raise ValueError('Could not safely extract BGP neighbor summary')
    return result


def route_parser(text: str, rows: list[dict] | None) -> dict:
    result={}
    if rows:
        for r in rows:
            prefix=_first(r,'network','prefix','route')
            if not prefix:continue
            source=_first(r,'protocol','route_type','type')
            nh=_first(r,'next_hop','nexthop','via')
            iface=_first(r,'interface','outgoing_interface')
            info={}
            if source is not None:info['source']=str(source)
            if nh is not None:info['next_hop']=str(nh)
            if iface is not None:info['interface']=normalize_interface(iface)
            if info:result[str(prefix)]=info
    if not result:
        for line in text.splitlines():
            m=re.match(r'^\s*([A-Z*]+)\s+(\d{1,3}(?:\.\d{1,3}){3}/\d{1,2})\s+(.+)$',line)
            if not m:continue
            rest=m.group(3)
            via=re.search(r'\bvia\s+(\d{1,3}(?:\.\d{1,3}){3})',rest)
            connected=re.search(r'directly connected,\s*(\S+)',rest)
            result[m.group(2)]={'source':m.group(1).replace('*',''),
                   'next_hop':via.group(1) if via else None,
                   'interface':normalize_interface(connected.group(1)) if connected else None}
    if not result: raise ValueError('No route prefixes found')
    return result


def security_parser(text: str, rows: list[dict] | None) -> dict:
    result={}
    if rows:
        for r in rows:
            name=_first(r,'port','interface','secure_port')
            action=_first(r,'security_action','action','violation_mode')
            maximum=_int(_first(r,'max_secure_addr','maxsecureaddr','maximum','max_secure_addresses'))
            if name and action is not None:
                entry={'action':str(action).lower()}
                if maximum is not None:entry['maximum']=maximum
                result[normalize_interface(name)]=entry
    if not result:
        for line in text.splitlines():
            m=re.match(r'^\s*(\S+\d+(?:/\d+){1,3})\s+(\d+)\s+\d+\s+\d+\s+(\S+)\s*$',line)
            if m:result[normalize_interface(m.group(1))]={'maximum':int(m.group(2)),'action':m.group(3).lower()}
    if not result:raise ValueError('No port-security rows found')
    return result


def error_counters_parser(text: str, rows: list[dict] | None) -> dict:
    """Compare error PRESENT, not absolute counters (which reset on reboot).

    Nonzero errors after the upgrade trigger CHANGE if previously absent;
    absolute counter deltas are intentionally NOT used.
    """
    result={}
    if rows:
        for r in rows:
            name=_first(r,'port','interface')
            if not name:continue
            values=[_int(_first(r,key)) for key in
                    ('align','fcs','xmit','rcv','under','discard','fcs_err','xmit_err','rcv_err')]
            values=[v for v in values if v is not None]
            if values:result[normalize_interface(name)]={'error_present':any(v>0 for v in values)}
    if not result:
        for line in text.splitlines():
            parts=line.split()
            if len(parts)==7 and IFACE.match(parts[0]) and all(_int(x) is not None for x in parts[1:]):
                result[normalize_interface(parts[0])]={'error_present':any(int(x)>0 for x in parts[1:])}
    if not result:raise ValueError('No interface error counter rows found')
    return result


def env_parser(text: str, rows: list[dict] | None) -> dict:
    result={}
    for line in text.splitlines():
        m=re.match(r'^(.+?)(?:\s+is\s+|\s+Status:\s*)(OK|Failed|Faulty|Not Present|Bad)\b',line,re.I)
        if m:result[m.group(1).strip().lower()]=m.group(2).upper()
    if not result:raise ValueError('No environment component statuses found')
    return result


def stp_parser(text: str, rows: list[dict] | None) -> dict:
    result={}
    for line in text.splitlines():
        m=re.match(r'^\s*VLAN(\d+)\s+(\d+)\s+([0-9a-fA-F.]+)\s+(\d+)\s+\d+\s+\d+\s+\d+\s+(.+)$',line)
        if m:result[str(int(m.group(1)))]={'root_id':m.group(3).lower(), 'root_port':m.group(5).strip()}
    if not result:raise ValueError('STP root rows not found')
    return result


def trunk_parser(text: str, rows: list[dict] | None) -> dict:
    result={}
    if '(No trunk interfaces configured)' in text:
        return result
    # Some NTC templates expose one record per trunk with allowed VLANs.
    if rows:
        for r in rows:
            port=_first(r,'port','interface')
            if not port:continue
            result[normalize_interface(port)]={k:str(r[k]) for k in
              ('status','native_vlan','vlans_allowed','vlans_allowed_active') if k in r}
    if not result:
        raise ValueError('Trunk details not parsed')
    return result


def etherchannel_parser(text: str, rows: list[dict] | None) -> dict:
    if re.search(r'Number of channel-groups in use:\s*0',text):return {}
    result={}
    if rows:
        for r in rows:
            channel=_first(r,'port_channel','po','port_channel_interface')
            if channel:
                result[str(channel)]={'protocol':str(_first(r,'protocol',default='')),
                    'members':sorted(str(_first(r,'ports',default='')).split(','))}
    if not result:raise ValueError('EtherChannel data not parsed')
    return result

# This registry is the only place where commands are mapped to our common data model.
# A template for an unlisted command can still parse, but is NOT automatically trusted.
NORMALIZERS = {
 'show version':('system','os_version',version_parser),
 'show interface status':('interfaces',None,status_parser),
 'show interfaces description':('interfaces',None,description_parser),
 'show ip interface brief':('interfaces',None,brief_parser),
 'show vlan brief':('vlans',None,vlans_parser),
 'show ip bgp summary':('routing','bgp',bgp_parser),
 'show ip route':('routing','routes',route_parser),
 'show port-security':('security','port_security',security_parser),
 'show interfaces counters errors':('interfaces',None,error_counters_parser),
 'show environment all':('hardware','environment',env_parser),
 'show spanning-tree root':('layer2','stp_roots',stp_parser),
 'show interfaces trunk':('layer2','trunks',trunk_parser),
 'show etherchannel summary':('layer2','etherchannels',etherchannel_parser),
}


def _merge_dict(dest: dict, incoming: dict) -> None:
    for key, value in incoming.items():
        if key not in dest:
            dest[key]=value
        elif isinstance(dest[key],dict) and isinstance(value,dict):
            _merge_dict(dest[key],value)
        elif dest[key] != value:
            # Different CLI commands may express equivalent states differently;
            # don't silently clobber an earlier result.
            dest.setdefault('_conflicts',{})[key]=[dest[key],value]


def parse_capture(path: str | Path, *, platform: str='cisco_ios', snapshot: str | None = None,
                  templates_dir: str | Path | None = None) -> dict:
    """Return model + coverage from a TXT capture; read-only, no SSH calls."""
    path=Path(path)
    text=path.read_text(encoding='utf-8-sig',errors='replace')
    commands=extract_commands(text)
    host_match=re.search(r'^HOSTNAME:\s*(\S+)',text,re.M)
    target_match=re.search(r'^TARGET:\s*(\S+)',text,re.M)
    device=(host_match.group(1) if host_match else target_match.group(1) if target_match else path.stem)
    selected_dir = resolve_templates_dir(templates_dir)
    model: dict[str,dict] = {}
    coverage: dict[str,dict] = {}
    for command, body in commands.items():
        if not body or CLI_ERROR.search(body):
            coverage[command]={'status':'COMMAND_ERROR' if CLI_ERROR.search(body) else 'EMPTY'}
            continue
        if command=='show running-config':
            coverage[command]={'status':'SKIPPED_SENSITIVE','reason':'No raw configuration stored in JSON'}
            continue
        result=textfsm_parse(command,body,platform,selected_dir)
        rows=result.rows
        if command not in NORMALIZERS:
            status = 'PARSED_UNMAPPED' if rows is not None else ('PARSE_ERROR' if result.error else 'UNSUPPORTED')
            coverage[command] = {'status': status, 'parser': result.parser,
                                 'records':len(rows) if rows is not None else 0}
            if result.template:coverage[command]['template']=result.template
            if result.error:coverage[command]['error']=result.error
            continue
        section,key,parser=NORMALIZERS[command]
        try:
            normalized=parser(body,rows)
            if section=='system' and key=='os_version':
                model.setdefault('system',{}).update(normalized)
            elif section=='interfaces' or section=='vlans':
                _merge_dict(model.setdefault(section,{}),normalized)
            else:
                existing=model.setdefault(section,{})
                if key is not None:
                    if key not in existing:existing[key]=normalized
                    elif isinstance(existing[key],dict):_merge_dict(existing[key],normalized)
                else:_merge_dict(existing,normalized)
            coverage[command]={'status':'NORMALIZED',
                               'parser':result.parser if rows is not None else 'builtin',
                               'section':section,'records':len(normalized) if isinstance(normalized,dict) else 1}
            if rows is not None and result.template:coverage[command]['template']=result.template
        except (ValueError,TypeError,KeyError) as exc:
            coverage[command]={'status':'PARSE_ERROR','error':str(exc),
                               'parser':result.parser if rows is not None else 'builtin'}
            if result.template:coverage[command]['template']=result.template
    return {'schema_version':1,'metadata':{'device':device,'source':str(path.name),'snapshot':snapshot,
           'platform':platform,'parsed_at':datetime.now().astimezone().isoformat(timespec='seconds'),
           'command_count':len(commands),'templates_dir':str(selected_dir) if selected_dir else None},'model':model,'coverage':coverage}
