"""Semantic normalizers for the 22 previously PARSED_UNMAPPED IOS-XE commands.

IMPORTANT:
- Each function accepts (raw_command_text, optional_TextFSM_records).
- The returned model contains *selected operational evidence*, NOT a dump of
  TextFSM rows. Dynamic counters, ages and event messages are excluded.
- Explicit empty/disabled output is a supported state; unknown output raises
  ValueError instead of claiming PASS.
- All captures are read-only: no SSH commands and no configuration changes.
"""
from __future__ import annotations

import re
from typing import Any


IFACE = re.compile(r'^(?:Gi|Te|Tw|Fo|Fa|Hu|Eth|Po|Vl|Lo|GigabitEthernet|TenGigabitEthernet|TwentyFiveGigE|FortyGigabitEthernet|HundredGigE|Port-channel|Vlan|Loopback)\d',re.I)

def val(row: dict, *names: str, default: Any = None) -> Any:
    lower = {str(k).lower():v for k,v in row.items()}
    for name in names:
        result = lower.get(name.lower())
        if result is not None and result != '':return result
    return default

def iface(value: Any) -> str:
    s=str(value).strip()
    if not s:return s
    for a,b in [('Gi','GigabitEthernet'),('Te','TenGigabitEthernet'),('Tw','TwentyFiveGigE'),('Fo','FortyGigabitEthernet'),('Fa','FastEthernet'),('Po','Port-channel'),('Vl','Vlan'),('Lo','Loopback')]:
        if re.match(r'^'+a+r'\d',s,re.I):return b+s[len(a):]
    # CDP sometimes prints 'Ten 1/1/1', 'Gig 1/0/1'
    m=re.fullmatch(r'(?i)(Ten|Gig|Fas|Eth|Twe|For)\s+(\d+(?:/\d+){1,3})',s)
    if m:
        return {'ten':'TenGigabitEthernet','gig':'GigabitEthernet','fas':'FastEthernet','eth':'Ethernet','twe':'TwentyFiveGigE','for':'FortyGigabitEthernet'}[m.group(1).lower()]+m.group(2)
    return s

def integer(x: Any) -> int | None:
    try:return int(str(x).strip().replace(',',''))
    except (ValueError,TypeError):return None

def nonempty_rows(rows: list[dict] | None, names: tuple[str, ...]) -> list[dict]:
    return [r for r in (rows or []) if any(val(r,n) is not None for n in names)]

def clock(text: str, rows: list[dict] | None) -> dict:
    source=re.search(r'(?im)^\s*Time source is\s+(\S+)',text)
    if source:return {'time_source':source.group(1).upper()}
    # On platforms not showing the source, we cannot infer time sync from clock alone.
    if re.search(r'(?m)\b\d{1,2}:\d{2}:\d{2}(?:\.\d+)?\s+\S+\s+\w+\s+\w+\s+\d+\s+\d{4}',text):
        return {'clock_readable':True}
    raise ValueError('Clock output not recognized')

def module(text: str, rows: list[dict] | None) -> dict:
    result={}
    for r in rows or []:
        serial=val(r,'serial','submodule_serial')
        model=val(r,'model','submodule_model')
        mod=val(r,'module')
        if model and serial:
            key=str(serial).strip()
            result[key]={'model':str(model).strip(),'module':str(mod or '').strip()}
            status=val(r,'status','submodule_status')
            if status:result[key]['status']=str(status).strip().lower()
    if not result:
        for line in text.splitlines():
            p=line.split()
            if len(p)>=7 and p[0].isdigit() and p[1].isdigit() and re.search(r'\d',p[2]) and re.fullmatch(r'[A-Z0-9-]{7,}',p[3],re.I):
                result[p[3]]={'model':p[2],'module':p[0]}
    if not result:raise ValueError('No module identity records found')
    return result

def license_summary(text: str, rows: list[dict] | None) -> dict:
    result={}
    for k,pattern in [('smart_enabled',r'(?im)^Smart Licensing is\s+(ENABLED|DISABLED)'),('registration',r'(?im)^Registration:\s*(.+)$'),('authorization',r'(?im)^License Authorization:\s*(.+)$')]:
        m=re.search(pattern,text)
        if m:result[k]=m.group(1).strip().lower()
    use={}
    for r in rows or []:
        name=val(r,'license')
        if name:use[str(name).lower()]={'status':str(val(r,'status',default='unknown')).strip().lower()}
    if not use:
        for line in text.splitlines():
            m=re.match(r'^\s*([\w.-]+)\s+\(.+?\)\s+\d+\s+(IN USE|NOT IN USE|AUTHORIZED|NOT AUTHORIZED|EVAL(?:UATION)?|EXPIRED)',line,re.I)
            if m:use[m.group(1).lower()]={'status':m.group(2).lower()}
    if use:result['licenses']=use
    if not result:raise ValueError('No licensing state found')
    return result

def counters(text: str, rows: list[dict] | None) -> dict:
    """Only report interface presence: absolute counters reset on reload."""
    ports=set()
    for r in rows or []:
        p=val(r,'interface','port')
        if p and IFACE.match(str(p)):ports.add(iface(p))
    if not ports:
        for line in text.splitlines():
            p=line.split()
            if len(p)>2 and IFACE.match(p[0]) and any(integer(v) is not None for v in p[1:]):ports.add(iface(p[0]))
    if not ports:raise ValueError('No interface counter rows found')
    return {port:{'counter_collection_present':True} for port in sorted(ports)}

def spanning_tree_summary(text: str, rows: list[dict] | None) -> dict:
    m=re.search(r'(?im)^Switch is in\s+(\S+?)\s+mode',text)
    if not m:m=re.search(r'(?im)^Spanning tree enabled protocol\s+(\S+)',text)
    if not m:
        for r in rows or []:
            mode=val(r,'mode')
            if mode:m=type('Match',(),{'group':lambda self,i:str(mode)})() ;break
    if not m:raise ValueError('STP mode not found')
    mode=m.group(1).strip().lower()
    return {'mode':mode}

def _duration_is_positive(value: str) -> bool | None:
    if re.fullmatch(r'(?:\d+:\d{2}:\d{2}|(?:\d+[ywdhms])+)', value, re.I):
        return any(int(part) for part in re.findall(r'\d+', value))
    return None


def interface_link(text: str, rows: list[dict] | None) -> dict:
    """Infer state only from unambiguous timer combinations; never diff durations."""
    lines = text.expandtabs().splitlines()
    states = {}
    for i, line in enumerate(lines):
        header = re.fullmatch(r'\s*Port\s+Name\s+(Down\s+Time)\s+(Up\s+Time)\s*', line, re.I)
        if not header:
            continue
        for row in lines[i + 1:]:
            if not row.strip() or re.fullmatch(r'[\s=-]+', row):
                continue
            port = row.split()[0]
            if not IFACE.match(port):
                raise ValueError('Unrecognized row in the link timer table')
            # Read the fixed positions from the header, not the port description.
            down = row[header.start(1):header.start(2)].strip()
            up = row[header.start(2):].strip()
            if _duration_is_positive(down) is False and _duration_is_positive(up) is True:
                state = 'up'
            elif _duration_is_positive(down) is True and not up:
                state = 'down'
            else:
                raise ValueError(f'Ambiguous link timers for {iface(port)}')
            states[iface(port)] = {'link_table_state': state}
        break
    else:
        for line in lines:
            m = re.match(r'^\s*(\S+)\s+(up|down|admin-down|disabled|notconnect)\s+', line, re.I)
            if m and IFACE.match(m[1]):
                states[iface(m[1])] = {'link_table_state': m[2].lower()}
        if not states:
            for r in rows or []:
                port = val(r, 'port', 'interface')
                state = str(val(r, 'link_state', 'status', 'state', default='')).lower()
                if port and state in ('up', 'down', 'admin-down', 'disabled', 'notconnect'):
                    states[iface(port)] = {'link_table_state': state}
    if not states:
        raise ValueError('No link state rows found (dates alone are not link state)')
    return states

def transceivers(text: str, rows: list[dict] | None) -> dict:
    state={}
    for r in rows or []:
        port=val(r,'interface','port')
        if port and IFACE.match(str(port)):
            state[iface(port)]={'present':True}
    for m in re.finditer(r'(?im)^\s*(\S+)\s+Transceiver is not present\b',text):
        if IFACE.match(m.group(1)):state[iface(m.group(1))]={'present':False}
    for line in text.splitlines():
        p=line.split()
        if len(p)>4 and IFACE.match(p[0]) and re.fullmatch(r'[-+]?\d+(?:\.\d+)?',p[1]):
            state[iface(p[0])]={'present':True}
    if not state:raise ValueError('No optic presence indicators found')
    return state

def mac_table(text: str, rows: list[dict] | None) -> dict:
    """Only compare configured STATIC MACs. Learned dynamic entries are ephemeral."""
    static={}; seen=False
    for r in rows or []:
        mac=val(r,'destination_address','mac_address');t=str(val(r,'type',default='')).lower()
        if mac:seen=True
        if mac and 'static' in t:
            static[str(mac).lower()]={'vlan':str(val(r,'vlan_id','vlan',default='')),
                'port':str(val(r,'destination_port','port',default=''))}
    for line in text.splitlines():
        m=re.match(r'^\s*(\d+)\s+([0-9a-fA-F.]{14})\s+(STATIC|DYNAMIC)\s+(.+)$',line,re.I)
        if m:
            seen=True
            if m.group(3).upper()=='STATIC':static[m.group(2).lower()]={'vlan':m.group(1),'port':iface(m.group(4).strip())}
    if not seen and not re.search(r'(?i)no\s+mac\s+(?:address|entries)',text):raise ValueError('MAC table output not recognized')
    return {'static_entries':static}

def mac_count(text: str, rows: list[dict] | None) -> dict:
    """Detect complete disappearance of MAC learning, but ignore exact counts."""
    matches=re.findall(r'(?im)^\s*(?:Dynamic Address Count|Dynamic MAC Addresses)\s*:\s*(\d+)',text)
    if matches:return {'dynamic_learning_present':int(matches[-1])>0}
    for r in rows or []:
        n=integer(val(r,'dynamic'))
        if n is not None:return {'dynamic_learning_present':n>0}
    raise ValueError('Dynamic MAC count not found')

def arp(text: str, rows: list[dict] | None) -> dict:
    """Preserve VLAN/interface ARP presence, ignore IP/MAC and entry age."""
    states={}; found=False
    for r in rows or []:
        ip=val(r,'ip_address','address');port=val(r,'interface')
        if ip and port:
            found=True;states[iface(port)]={'arp_entries_present':True}
    if not found:
        for line in text.splitlines():
            m=re.match(r'^\s*Internet\s+\d{1,3}(?:\.\d{1,3}){3}\s+\S+\s+\S+\s+ARPA\s+(\S+)',line,re.I)
            if m:found=True;states[iface(m.group(1))]={'arp_entries_present':True}
    if not found:
        if re.search(r'(?i)(?:no\s+arp\s+entries|0\s+entries)',text):return {}
        raise ValueError('No recognizable ARP entries')
    return states

def route_summary(text: str, rows: list[dict] | None) -> dict:
    sources={}
    for r in rows or []:
        name=val(r,'route_source')
        if name and str(name).strip().lower()!='total':
            sub=integer(val(r,'subnets'));net=integer(val(r,'networks'))
            if sub is not None or net is not None:sources[str(name).strip().lower()]={'prefix_count':(sub or 0)+(net or 0)}
    if not sources:
        for line in text.splitlines():
            m=re.match(r'^\s*(connected|local|bgp\s+\d+|ospf(?:\s+\d+)?|static|eigrp\s+\d+)\s+(\d+)\s+(\d+)\s+\d+\s+\d+',line,re.I)
            if m:sources[m.group(1).lower()]={'prefix_count':int(m.group(2))+int(m.group(3))}
    if not sources:raise ValueError('Route source counts not found')
    return sources

def ip_protocols(text: str, rows: list[dict] | None) -> dict:
    result={}
    for r in rows or []:
        p=val(r,'protocol')
        if p:result[str(p).lower()]={'configured':True}
    for m in re.finditer(r'(?im)^Routing Protocol is\s+"([^"]+)"',text):result[m.group(1).lower()]={'configured':True}
    if not result:
        if re.search(r'(?i)(?:no routing protocols|routing is not enabled)',text):return {}
        raise ValueError('Routing protocol identities not found')
    return result

def _neighbor_lines(rows: list[dict] | None, name_keys:tuple[str,...], local_keys:tuple[str,...], remote_keys:tuple[str,...]) -> dict:
    result={}
    for r in rows or []:
        name=val(r,*name_keys); local=val(r,*local_keys);remote=val(r,*remote_keys)
        if name and local:
            key=iface(local)
            result[key]={'neighbor':str(name).strip()}
            if remote:result[key]['remote_interface']=iface(remote)
    return result

def cdp(text: str, rows: list[dict] | None) -> dict:
    result=_neighbor_lines(rows,('neighbor_name','device_id','destination_host'),('local_interface','local_port'),('neighbor_interface','port_id'))
    if not result:
        for line in text.splitlines():
            # Split table by column positions, since Capability/Platform contain spaces.
            m=re.match(r'^\s*(\S+)\s+((?:Gig|Ten|Fas|Eth)\s+\d+(?:/\d+)+)\s+\d+\s+.+?\s+(\S+)\s+((?:Gig|Ten|Fas|Eth)\s+\d+(?:/\d+)+)\s*$',line,re.I)
            if m:result[iface(m.group(2))]={'neighbor':m.group(1),'remote_interface':iface(m.group(4)),'platform':m.group(3)}
    if not result:
        if re.search(r'(?i)(?:total\s+cdp\s+entries\s+displayed\s*:\s*0|no\s+cdp\s+neighbors)',text):return {}
        raise ValueError('CDP neighbors could not be parsed')
    # Platform can be omitted by some CLI formats; never force it into compare.
    for x in result.values():x.pop('platform',None)
    return result

def cdp_detail(text: str, rows: list[dict] | None) -> dict:
    result=_neighbor_lines(rows,('neighbor_name','device_id'),('local_interface',),('neighbor_interface',))
    if not result:
        for block in re.split(r'(?=^-{5,}\s*$)',text,flags=re.M):
            name=re.search(r'(?im)^Device ID:\s*(\S+)',block)
            line=re.search(r'(?im)^Interface:\s*([^,]+),\s*Port ID\s*\(outgoing port\):\s*(\S+)',block)
            if name and line:result[iface(line.group(1))]={'neighbor':name.group(1),'remote_interface':iface(line.group(2))}
    if not result:
        if re.search(r'(?i)no\s+cdp\s+neighbors',text):return {}
        raise ValueError('CDP detail contains no recognized neighbors')
    return result

def lldp(text: str, rows: list[dict] | None) -> dict:
    if re.search(r'(?i)LLDP is not enabled globally',text):return {'enabled':False,'neighbors':{}}
    result=_neighbor_lines(rows,('neighbor_name','system_name'),('local_interface',),('neighbor_interface',))
    if not result:
        if re.search(r'(?i)no lldp neighbors found',text):return {'enabled':True,'neighbors':{}}
        # Real LLDP table without TextFSM rows may require the supplied template.
        raise ValueError('LLDP neighbors table not parsed')
    return {'enabled':True,'neighbors':result}

def lldp_detail(text: str, rows: list[dict] | None) -> dict:
    if re.search(r'(?i)LLDP is not enabled globally',text):return {'enabled':False,'neighbors':{}}
    result=_neighbor_lines(rows,('neighbor_name','system_name'),('local_interface',),('neighbor_interface','neighbor_port_id'))
    if not result:
        if re.search(r'(?i)no lldp neighbors found',text):return {'enabled':True,'neighbors':{}}
        raise ValueError('LLDP detailed neighbors not parsed')
    return {'enabled':True,'neighbors':result}

def auth_sessions(text: str, rows: list[dict] | None) -> dict:
    if re.search(r'(?im)^[ \t]*No (?:authentication sessions match supplied criteria|sessions currently exist)\.?[ \t]*$', text):
        return {'has_sessions': False}
    sessions={}
    for r in rows or []:
        p=val(r,'interface');status=val(r,'status')
        if p and status:sessions[iface(p)]={'status':str(status).strip().lower()}
    if not sessions:raise ValueError('Authentication sessions not parsed')
    return {'has_sessions':True,'sessions':sessions}

def dhcp_bindings(text: str, rows: list[dict] | None) -> dict:
    # Bindings are dynamic and may recover gradually after reload. Compare only
    # whether there are any (loss of all bindings may be operationally relevant).
    match=re.search(r'(?i)Total number of bindings\s*:\s*(\d+)',text)
    if match:return {'has_bindings':int(match.group(1))>0}
    if rows is not None:return {'has_bindings':bool(nonempty_rows(rows,('ip_address',)))}
    raise ValueError('DHCP snooping binding count not parsed')

def device_tracking(text: str, rows: list[dict] | None) -> dict:
    if re.search(r'(?i)No entries found',text):return {'has_entries':False}
    if rows is not None:
        return {'has_entries':bool(nonempty_rows(rows,('address','ip_address')))}
    raise ValueError('Device tracking database not parsed')

def cpu_sorted(text: str, rows: list[dict] | None) -> dict:
    m=re.search(r'(?i)five\s+minutes:\s*(\d+)%',text)
    if m:v=int(m.group(1))
    elif rows:
        v=integer(val(rows[0],'cpu_usage_5_min'))
    else:v=None
    if v is None:raise ValueError('5-minute CPU utilization not found')
    return {'cpu_high_5min':v>=85}

def memory_sorted(text: str, rows: list[dict] | None) -> dict:
    m=re.search(r'(?im)^\s*Processor Pool Total:\s*(\d+)\s+Used:\s*(\d+)',text)
    if m:total,used=int(m.group(1)),int(m.group(2))
    elif rows:
        total=integer(val(rows[0],'memory_total'));used=integer(val(rows[0],'memory_used'))
    else:total=used=None
    if total is None or used is None or total<=0:raise ValueError('Processor memory pool not found')
    return {'memory_pressure':used/total>=0.90}

def logging(text: str, rows: list[dict] | None) -> dict:
    state=re.search(r'(?im)^\s*Syslog logging:\s*(enabled|disabled)',text)
    if not state:raise ValueError('Syslog logging state not found')
    targets=sorted(set(re.findall(r'(?im)^\s*Logging to\s+((?:\d{1,3}\.){3}\d{1,3})\b',text)))
    return {'enabled':state.group(1).lower()=='enabled','remote_servers':targets}

# Entries share the same schema as snapshotchecks.parsing.NORMALIZERS:
# command -> (model section, nested key or None, callback)
EXTRA_NORMALIZERS={
 'show clock':('system',None,clock),
 'show module':('hardware','modules',module),
 'show license summary':('system','licensing',license_summary),
 'show interfaces counters':('interfaces',None,counters),
 'show spanning-tree summary':('layer2','stp_summary',spanning_tree_summary),
 'show interfaces link':('interfaces',None,interface_link),
 'show interfaces transceiver detail':('hardware','transceivers',transceivers),
 'show mac address-table':('layer2','mac_static',mac_table),
 'show mac address-table count':('layer2','mac_learning',mac_count),
 'show ip arp':('interfaces',None,arp),
 'show ip route summary':('routing','route_summary',route_summary),
 'show ip protocols':('routing','protocols',ip_protocols),
 'show cdp neighbors':('layer2','cdp',cdp),
 'show cdp neighbors detail':('layer2','cdp_detail',cdp_detail),
 'show lldp neighbors':('layer2','lldp',lldp),
 'show lldp neighbors detail':('layer2','lldp_detail',lldp_detail),
 'show authentication sessions':('security','auth_sessions',auth_sessions),
 'show ip dhcp snooping binding':('security','snooping_bindings',dhcp_bindings),
 'show device-tracking database':('security','device_tracking',device_tracking),
 'show processes cpu sorted':('hardware','cpu_health',cpu_sorted),
 'show processes memory sorted':('hardware','memory_health',memory_sorted),
 'show logging':('system','logging',logging),
}
