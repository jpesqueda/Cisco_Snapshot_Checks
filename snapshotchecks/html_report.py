"""Self-contained offline HTML report: semantic PRE/POST tables in accordions.

Only allowlisted normalized fields appear in tables; raw running-config never
enters this page. All model-derived strings are HTML-escaped.
"""
from __future__ import annotations

import html
import json

COLORS = {
    'PASS': '#14804a',
    'EXPECTED': '#1877aa',
    'CHANGE': '#a96d00',
    'ERROR': '#b42336',
    'MISSING': '#b42336',
    'INCOMPLETE': '#a96d00',
    'NOT_EVALUATED': '#667085',
    'UNSUPPORTED': '#667085',
}


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def format_value(value: object, exists: bool = True) -> str:
    if not exists:
        return '—'
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return str(value)


def pill(status: str) -> str:
    return f'<span class="status" data-value="{esc(status)}">{esc(status)}</span>'


def make_html_report(report: dict) -> str:
    device = esc(report['device'])
    source = esc(report['snapshot_from'])
    target = esc(report['snapshot_to'])
    overall = esc(report['overall_status'])
    expected = esc(report.get('expected_version') or 'Not specified')
    engine = esc(report.get('comparison_engine', 'unknown'))
    sections = []
    for name, section in report['sections'].items():
        rows = section.get('rows', [])
        changed = sum(r['status'] in ('CHANGE', 'ERROR', 'MISSING') for r in rows)
        expected_changes = sum(r['status'] == 'EXPECTED' for r in rows)
        table_rows = []
        for row in rows:
            status = row['status']
            old = format_value(row.get('old'), row.get('old_present', True))
            new = format_value(row.get('new'), row.get('new_present', True))
            table_rows.append(
                f'<tr data-status="{esc(status)}">'
                f'<th scope="row">{esc(row["field"])}</th>'
                f'<td><code>{esc(old)}</code></td>'
                f'<td><code>{esc(new)}</code></td>'
                f'<td>{pill(status)}</td></tr>'
            )
        body = '<div class="table-wrap"><table><thead><tr><th>FIELD</th><th>PRE</th><th>POST</th><th>STATUS</th></tr></thead>'
        if table_rows:
            body += '<tbody>' + ''.join(table_rows) + '</tbody></table></div>'
        else:
            body += '</table></div><p class="empty">' + esc(section.get('reason') or 'No evaluated fields in this section.') + '</p>'
        is_open = bool(changed or expected_changes or section['status'] in ('ERROR', 'MISSING', 'NOT_EVALUATED'))
        overview = f'{len(rows)} fields · {changed} changes'
        if expected_changes:
            overview += f' · {expected_changes} expected'
        sections.append(
            f'<details class="section" data-section-status="{esc(section["status"])}" {"open" if is_open else ""}>'
            f'<summary><span class="section-name">{esc(name.upper())}</span>'
            f'<span class="section-meta">{esc(overview)}</span>{pill(section["status"])}</summary>'
            f'{body}</details>'
        )
    uncovered_rows = []
    for cmd, values in report.get('commands', {}).items():
        if values['status'] == 'NORMALIZED':
            continue
        uncovered_rows.append(
            f'<tr><th scope="row">{esc(cmd)}</th><td>{esc(values["first"])}</td>'
            f'<td>{esc(values["second"])}</td><td>{pill(values["status"])}</td></tr>'
        )
    coverage = ('<div class="table-wrap"><table><thead><tr><th>COMMAND</th><th>FROM</th><th>TO</th><th>STATUS</th></tr></thead>'
                '<tbody>' + (''.join(uncovered_rows) if uncovered_rows else '<tr><td colspan="4">All commands are normalized.</td></tr>')
                + '</tbody></table></div>')
    note = esc(report.get('note', 'Only normalized allowlisted fields were evaluated.'))
    document = '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__DEVICE__ · Snapshot Compare</title>
<style>
:root { color-scheme: light; font-family: Segoe UI, Inter, system-ui, sans-serif; color: #202939;
--border: #d8dee8; --muted: #64748b; --surface:#fff; --background:#f7f9fc; --accent:#1e4672; }
* { box-sizing: border-box; }
body { background:var(--background); margin:0; padding:28px max(18px,calc((100vw - 1220px)/2)); }
header { padding:23px 26px; background:var(--surface); border:1px solid var(--border); border-radius:14px; }
h1 { font-size:1.45rem; letter-spacing:.015em; margin:0 0 10px; }
h2 { font-size:1.08rem; margin:28px 0 10px; }
.meta {color:var(--muted); font-size:.92rem; }
.summary {display:flex; gap:15px; flex-wrap:wrap; align-items:center; margin-top:15px;}
.snapshot { flex:1 1 200px; border-radius:9px; background:#f2f6fb; padding:12px 15px; }
.snapshot strong { display:block; margin-top:6px; font-size:1.03rem; }
.summary-label { color:var(--muted); text-transform:uppercase; font-size:.76rem; letter-spacing:.04em; }
.toolbar { display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin:17px 0 10px; }
button, input {font:inherit;} button { border:1px solid #bec9d8; padding:8px 13px; background:white; border-radius:7px; cursor:pointer; }
button:hover {background:#edf2f8;} button:focus-visible, summary:focus-visible, input:focus-visible {outline:2px solid var(--accent);outline-offset:2px;}
.toggle { display:flex;gap:7px;align-items:center;white-space:nowrap;font-size:.91rem; margin-left:auto; }
.search { border:1px solid #bec9d8; padding:9px 11px; border-radius:7px; flex:1 1 170px; min-width:140px; max-width:280px; }
.section { background:#fff;border:1px solid var(--border);border-radius:10px;margin:10px 0;overflow:hidden; }
.section summary { list-style:none; cursor:pointer;padding:15px 18px;display:flex;gap:11px;align-items:center;flex-wrap:wrap; }
.section summary::-webkit-details-marker{display:none;}
.section summary:before {content:'▸';font-size:1.1em;color:#64748b;}
.section[open] summary:before{content:'▾';}
.section-name {font-weight:750;flex:1 1 140px;letter-spacing:.035em;}
.section-meta {color:var(--muted);font-size:.84rem;}
.status { display:inline-block; border-radius:7px; padding:4px 8px;font-size:.72rem;font-weight:750;
color:#475467;background:#eef0f4;white-space:nowrap; }
.status[data-value=PASS] {background:#e6f7ef;color:#116c43;}
.status[data-value=EXPECTED] {background:#e5f3ff;color:#175f8e;}
.status[data-value=CHANGE],.status[data-value=INCOMPLETE] {background:#fff3d7;color:#995b00;}
.status[data-value=ERROR],.status[data-value=MISSING] {background:#ffebe8;color:#a52933;}
.table-wrap {overflow:auto;max-height:520px;border-top:1px solid var(--border);}
table {border-collapse:collapse;width:100%;font-size:.87rem;} th,td {text-align:left; padding:10px 13px;border-bottom:1px solid #ebeff5;vertical-align:top;}
thead th {position:sticky;top:0;z-index:1;background:#eff3f9;color:#5c697a;font-size:.75rem;letter-spacing:.045em;}
tbody th {font-weight:550;min-width:200px;} td code {white-space:pre-wrap;word-break:break-word;font-family:Cascadia Code,Consolas,monospace;font-size:.82rem;}
tr[data-status=CHANGE],tr[data-status=ERROR] {background:#fffaf2;} tr[data-status=EXPECTED] {background:#f5faff;}
tr[hidden],details[hidden] {display:none;}
.empty,.footnote {color:var(--muted);font-size:.86rem;line-height:1.5;padding:4px 16px 15px;}
#coverage summary{font-weight:650;}
@media (max-width:700px) {body{padding:14px;}header{padding:17px;}.toggle{margin-left:0}.section summary{padding:12px}.snapshot{flex:1 1 100%}th,td{padding:9px;}}
</style></head><body>
<header>
<h1>CISCO SMART SNAPSHOT DIFF</h1><div class="meta">__DEVICE__</div>
<div class="summary"><div class="snapshot"><span class="summary-label">SNAPSHOT __FROM__ · PRE</span><strong>__FROM__</strong></div>
<div class="snapshot"><span class="summary-label">SNAPSHOT __TO__ · POST</span><strong>__TO__</strong></div>
<div>__OVERALL_PILL__</div></div>
<p class="meta">Expected IOS-XE: __EXPECTED__ &nbsp;·&nbsp; Comparison engine: __ENGINE__</p>
</header>
<h2>Expandable comparison sections</h2>
<div class="toolbar"><button type="button" id="expand">Expand all</button><button type="button" id="collapse">Collapse all</button>
<input id="search" class="search" placeholder="Search fields..." aria-label="Search fields">
<label class="toggle"><input type="checkbox" id="changes-only"> Changes only</label></div>
<div id="sections">__SECTIONS__</div>
<details class="section" id="coverage"><summary>COMMAND COVERAGE · __UNCOVERED__ requires review</summary>__COVERAGE__</details>
<p class="footnote">__NOTE__</p>
<script>
(function(){'use strict';
  const sections = [...document.querySelectorAll('#sections details.section')];
  const only = document.getElementById('changes-only');
  const search = document.getElementById('search');
  document.getElementById('expand').addEventListener('click',()=>sections.forEach(s=>s.open=true));
  document.getElementById('collapse').addEventListener('click',()=>sections.forEach(s=>s.open=false));
  function apply(){
    const term = search.value.toLocaleLowerCase().trim();
    sections.forEach(section=>{
      const rows=[...section.querySelectorAll('tbody tr[data-status]')];
      let visible=0;
      rows.forEach(row=>{
        const flagged = !['PASS'].includes(row.dataset.status);
        const matches = !term || row.textContent.toLocaleLowerCase().includes(term);
        row.hidden = (only.checked && !flagged) || !matches;
        if (!row.hidden) visible++;
      });
      const status=section.dataset.sectionStatus;
      const needsReview=['MISSING','ERROR','NOT_EVALUATED','INCOMPLETE'].includes(status);
      section.hidden = (only.checked || term) && visible===0 && !(needsReview && !term);
      if (term && visible>0) section.open=true;
    });
  }
  only.addEventListener('change',apply);
  search.addEventListener('input',apply);
  apply();
})();
</script></body></html>'''
    replacements = {
        '__DEVICE__': device, '__FROM__': source, '__TO__': target,
        '__OVERALL_PILL__': pill(overall), '__EXPECTED__': expected,
        '__ENGINE__': engine, '__SECTIONS__': ''.join(sections),
        '__UNCOVERED__': str(len(uncovered_rows)), '__COVERAGE__': coverage,
        '__NOTE__': note,
    }
    # Substitution only in static HTML slots, never in JavaScript code or data.
    for key, value in replacements.items():
        document = document.replace(key, value)
    return document
