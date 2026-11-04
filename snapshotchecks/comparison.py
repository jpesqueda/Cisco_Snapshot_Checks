"""Compare selected, normalized network state across any two snapshots.

DeepDiff is the preferred comparison backend. A small built-in recursive diff is
used only if DeepDiff is unavailable, and explicitly identified in the report.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_SECTIONS={
 'system': ['os_version'],
 'hardware': ['environment'],
 'interfaces': ['oper_status','description','access_vlan','l3_status','protocol','ip_address'],
 'vlans': ['name','status'],
 'routing': ['bgp','routes'],
 'layer2': ['stp_roots','trunks','etherchannels'],
 'security': ['port_security'],
}


def load_rules(path: Path | None) -> dict:
    result={'sections':{name:{'fields':fields} for name,fields in DEFAULT_SECTIONS.items()}}
    if path is None:return result
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError('YAML rules require pyyaml: python -m pip install pyyaml') from exc
    raw=yaml.safe_load(Path(path).read_text(encoding='utf-8')) or {}
    if not isinstance(raw,dict):raise ValueError('YAML rules must be a mapping')
    for key,settings in (raw.get('sections') or {}).items():
        if settings is False:
            result['sections'].pop(key,None)
        elif isinstance(settings,dict):
            result['sections'][key]=settings
    return result


def projection(section: str, obj: Any, rule: dict) -> dict:
    """Field allowlist: never compare the full parsed JSON blindly."""
    fields=rule.get('fields',[])
    if not isinstance(fields,list):raise ValueError(f'Section {section}: fields must be a list')
    if not isinstance(obj,dict):return {}
    if section in ('interfaces','vlans'):
        return {name:{f:attrs[f] for f in fields if f in attrs}
                for name,attrs in obj.items() if isinstance(attrs,dict)}
    return {f:obj[f] for f in fields if f in obj}


def _fallback_diff(left: Any,right: Any,path: str='root') -> dict[str,dict]:
    """Portable fallback used when DeepDiff cannot be imported."""
    change={}
    if isinstance(left,dict) and isinstance(right,dict):
        for k in sorted(set(left)|set(right)):
            branch=path+'['+repr(str(k))+']'
            if k not in left:change[branch]={'change':'added','old':None,'new':right[k]}
            elif k not in right:change[branch]={'change':'removed','old':left[k],'new':None}
            else:change.update(_fallback_diff(left[k],right[k],branch))
    elif isinstance(left,list) and isinstance(right,list):
        if sorted(map(str,left))!=sorted(map(str,right)):
            change[path]={'change':'changed','old':left,'new':right}
    elif left!=right:change[path]={'change':'changed','old':left,'new':right}
    return change


def differences(left: dict,right: dict) -> tuple[list[dict],str]:
    try:
        from deepdiff import DeepDiff
    except ImportError:
        raw=_fallback_diff(left,right)
        return [{'path':p,**entry} for p,entry in sorted(raw.items())],'builtin_fallback'
    try:
        dd=DeepDiff(left,right,ignore_order=True,verbose_level=2)
        raw=json.loads(dd.to_json()) if dd else {}
        changes=[]
        for kind,values in raw.items():
            if isinstance(values,dict):
                for path,value in values.items():
                    if isinstance(value,dict):
                        before=value.get('old_value',value.get('old_type'))
                        after=value.get('new_value',value.get('new_type'))
                    else:
                        before=None if kind.endswith('_added') else value
                        after=value if kind.endswith('_added') else None
                    changes.append({'path':path,'change':kind,'old':before,'new':after})
            elif isinstance(values,list):
                changes.extend({'path':str(p),'change':kind,'old':None,'new':None} for p in values)
        return sorted(changes,key=lambda x:x['path']),'deepdiff'
    except (TypeError,ValueError,AttributeError) as exc:
        raise RuntimeError('DeepDiff could not serialize comparison: '+str(exc)) from exc


def _flat_fields(value: Any, prefix: tuple[str, ...] = ()) -> dict[tuple[str, ...], Any]:
    """Flatten only the semantic allowlist, without adding raw command data.

    Lists are kept as leaf values to match DeepDiff(ignore_order=True). Empty
    dictionaries are kept as leaves so a removed empty branch stays visible.
    """
    if isinstance(value, dict):
        if not value:
            return {prefix: {}} if prefix else {}
        flattened = {}
        for key in sorted(value, key=str):
            flattened.update(_flat_fields(value[key], prefix + (str(key),)))
        return flattened
    return {prefix: value}


def _equivalent(a: Any, b: Any) -> bool:
    """Match DeepDiff's ignore_order for list comparisons in display rows."""
    if isinstance(a, list) and isinstance(b, list):
        def signature(item: Any) -> str:
            return json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
        return sorted(map(signature, a)) == sorted(map(signature, b))
    return a == b


def _label(section: str, parts: tuple[str, ...]) -> str:
    if not parts:
        return section
    if section == 'vlans' and len(parts) > 1:
        return 'VLAN ' + parts[0] + ' / ' + ' / '.join(parts[1:])
    return ' / '.join(parts)


def comparison_rows(section: str, left: dict, right: dict,
                    expected_version: str | None = None) -> list[dict]:
    """Store ALL compared fields for Collapsible HTML / TUI comparison tables.

    Values come only from the allowlisted normalized model. A missing key is
    different from an explicit JSON null.
    """
    before = _flat_fields(left)
    after = _flat_fields(right)
    output = []
    for path in sorted(set(before) | set(after)):
        old_present = path in before
        new_present = path in after
        old = before.get(path)
        new = after.get(path)
        status = 'PASS' if old_present and new_present and _equivalent(old, new) else 'CHANGE'
        if section == 'system' and path == ('os_version',) and expected_version:
            if not new_present:
                status = 'NOT_EVALUATED'
            elif str(new) != str(expected_version):
                status = 'ERROR'
            elif status == 'CHANGE':
                status = 'EXPECTED'
        output.append({
            'field': _label(section, path),
            'old': old, 'new': new,
            'old_present': old_present, 'new_present': new_present,
            'status': status,
        })
    return output


def compare_snapshots(a: dict,b: dict,rules: dict,expected_version: str | None=None) -> dict:
    model_a=a.get('model',{})
    model_b=b.get('model',{})
    results={}
    used_engine=None
    for name,policy in rules['sections'].items():
        pre=model_a.get(name)
        post=model_b.get(name)
        if pre is None and post is None:
            results[name]={'status':'NOT_EVALUATED','changes':[],
                'reason':'No normalized data in either snapshot','rows':[]}
            continue
        if pre is None or post is None:
            results[name]={'status':'MISSING','changes':[],
                'reason':'Normalized data missing in '+('first' if pre is None else 'second')+' snapshot','rows':[]}
            continue
        left=projection(name,pre,policy)
        right=projection(name,post,policy)
        changes,engine=differences(left,right)
        used_engine=engine
        rows=comparison_rows(name,left,right,expected_version)
        status='CHANGE' if changes else 'PASS'
        if not rows and not changes:
            status='NOT_EVALUATED'
        if name=='system' and expected_version:
            found=right.get('os_version')
            if found is None:
                status='NOT_EVALUATED'
                changes.append({'path':"root['os_version']",'change':'not_parsed','old':left.get('os_version'),'new':None})
            elif str(found)!=str(expected_version):
                status='ERROR'
                changes.append({'path':"root['expected_version']",'change':'expected_mismatch',
                                'old':expected_version,'new':found})
            elif changes and all(row['status'] in ('EXPECTED','PASS') for row in rows):
                status='EXPECTED'
        results[name]={'status':status,'changes':changes,'rows':rows}
    coverage_a=a.get('coverage',{})
    coverage_b=b.get('coverage',{})
    commands={}
    for name in dict.fromkeys([*coverage_a,*coverage_b]):
        ca=coverage_a.get(name,{}).get('status','MISSING')
        cb=coverage_b.get(name,{}).get('status','MISSING')
        commands[name]={'first':ca,'second':cb,
            'status': 'MISSING' if 'MISSING' in (ca,cb) else
                      'NORMALIZED' if ca==cb=='NORMALIZED' else
                      'UNSUPPORTED' if ca==cb=='UNSUPPORTED' else
                      'NOT_EVALUATED'}
    problem=any(x['status'] in ('CHANGE','ERROR','MISSING') for x in results.values())
    incomplete=any(x['status'] in ('MISSING','NOT_EVALUATED') for x in results.values()) or any(
        x['status'] not in ('NORMALIZED',) for x in commands.values())
    overall='CHANGE' if problem else 'INCOMPLETE' if incomplete else 'PASS'
    return {'schema_version':1,'device':b['metadata']['device'],
            'snapshot_from':a['metadata'].get('snapshot'),
            'snapshot_to':b['metadata'].get('snapshot'),
            'expected_version':expected_version,
            'comparison_engine':used_engine or 'not_used',
            'overall_status':overall,'sections':results,'commands':commands,
            'note':'Unsupported/unmapped outputs are not asserted healthy; PASS refers only to evaluated fields.'}
