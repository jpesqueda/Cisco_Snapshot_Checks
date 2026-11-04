"""Optional Textual Collapsible + DataTable comparison viewer for Windows terminals.

Offline viewer: it consumes the semantic comparison report and never connects to
network devices. Textual is loaded only when the user requests --tui.
"""
from __future__ import annotations

from .html_report import format_value


def launch_tui(reports: list[dict]) -> None:
    if not reports:
        raise ValueError('No reports available to display')
    try:
        from rich.text import Text
        from textual.app import App, ComposeResult
        from textual.containers import Horizontal, VerticalScroll
        from textual.widgets import Button, Checkbox, Collapsible, DataTable, Footer, Header, Select, Static
    except ImportError as exc:
        raise RuntimeError('The interactive viewer requires Textual: python -m pip install textual') from exc

    report_by_device = {r['device']: r for r in reports}
    names = sorted(report_by_device)
    all_sections = list(dict.fromkeys(section for report in reports for section in report['sections']))
    status_styles = {
        'PASS': 'green', 'EXPECTED': 'cyan', 'CHANGE': 'yellow',
        'ERROR': 'red', 'MISSING': 'red', 'NOT_EVALUATED': 'dim',
    }

    class SnapshotAccordion(App):
        TITLE = 'CISCO SNAPSHOT CHECKS'
        SUB_TITLE = 'Expandable PRE / POST comparison'
        CSS = '''
        Screen { background: $surface; }
        Header { dock: top; }
        #headline { margin: 1 2; height: 3; content-align: left middle;
                    border: round $primary; padding: 0 2; }
        #controls { height: 5; padding: 0 1; align: left middle; }
        #device { width: 35; min-width: 20; margin: 0 1; }
        #controls Button { margin: 0 1; min-width: 13; }
        #changes { width: 22; margin: 1 1; }
        #sections { height: 1fr; padding: 1 2; }
        Collapsible { height: auto; margin-bottom: 1; border: round $panel; }
        Collapsible DataTable { height: 13; width: 100%; }
        #coverage { border-top: solid $panel; padding: 1 2; height: 2; }
        Footer { dock: bottom; }
        '''
        BINDINGS = [('q', 'quit', 'Quit'), ('e', 'expand_all', 'Expand all'),
                    ('c', 'collapse_all', 'Collapse all'), ('f', 'toggle_changes', 'Changes only')]

        def __init__(self) -> None:
            super().__init__()
            self.current = names[0]
            self.changes_only = False
            self._tables_ready = False

        def compose(self) -> ComposeResult:
            yield Header(show_clock=False)
            yield Static('', id='headline')
            with Horizontal(id='controls'):
                yield Select([(x, x) for x in names], value=names[0], allow_blank=False, id='device')
                yield Button('Expand all [E]', id='expand')
                yield Button('Collapse all [C]', id='collapse')
                yield Checkbox('Changes only [F]', value=False, id='changes')
            with VerticalScroll(id='sections'):
                for index, section in enumerate(all_sections):
                    with Collapsible(title=section.upper(), collapsed=True, id=f'accordion-{index}'):
                        yield DataTable(id=f'table-{index}', cursor_type='row', zebra_stripes=True)
            yield Static('', id='coverage')
            yield Footer()

        def on_mount(self) -> None:
            for idx in range(len(all_sections)):
                table = self.query_one(f'#table-{idx}', DataTable)
                table.add_columns('FIELD', 'PRE', 'POST', 'STATUS')
                table.fixed_columns = 1
            self._tables_ready = True
            self.render_report(reset_expanded=True)

        def render_report(self, reset_expanded: bool = False) -> None:
            report = report_by_device[self.current]
            self.query_one('#headline', Static).update(
                f"{self.current}  |  Snapshot {report['snapshot_from']} -> {report['snapshot_to']}"
                f"  |  {report['overall_status']}"
            )
            uncovered = sum(data['status'] != 'NORMALIZED' for data in report.get('commands', {}).values())
            self.query_one('#coverage', Static).update(
                f"Coverage: {uncovered} command(s) need review | "
                "Results are semantic comparisons, not full device health checks"
            )
            for idx, name in enumerate(all_sections):
                section = report['sections'].get(name, {'status': 'NOT_EVALUATED', 'rows': []})
                rows = section.get('rows', [])
                remaining = [r for r in rows if not self.changes_only or r['status'] != 'PASS']
                widget = self.query_one(f'#accordion-{idx}', Collapsible)
                table = self.query_one(f'#table-{idx}', DataTable)
                status = section['status']
                flagged = sum(row['status'] in ('CHANGE','ERROR','MISSING') for row in rows)
                widget.title = f'{name.upper()}  [{status}]  {len(rows)} fields / {flagged} changes'
                widget.display = bool(remaining) or (
                    not self.changes_only or status in ('NOT_EVALUATED','MISSING','ERROR')
                )
                if reset_expanded:
                    widget.collapsed = not (status in ('EXPECTED','CHANGE','ERROR','MISSING'))
                table.clear()
                if not remaining:
                    if widget.display:
                        table.add_row('No evaluated fields', '—', '—', Text(status, style=status_styles.get(status,'dim')))
                else:
                    for row in remaining:
                        style = status_styles.get(row['status'], 'white')
                        table.add_row(
                            row['field'],
                            format_value(row.get('old'), row.get('old_present', True)),
                            format_value(row.get('new'), row.get('new_present', True)),
                            Text(row['status'], style=style),
                        )
                table.styles.height = min(16, max(4, len(remaining)+3))

        def on_select_changed(self, event: Select.Changed) -> None:
            if event.select.id != 'device' or event.value not in report_by_device:
                return
            self.current = str(event.value)
            # The selection may fire during widget mount; defer until tables exist.
            if self._tables_ready:
                self.render_report(reset_expanded=True)

        def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
            if event.checkbox.id == 'changes' and self._tables_ready:
                self.changes_only = event.value
                self.render_report()

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == 'expand':
                self.action_expand_all()
            elif event.button.id == 'collapse':
                self.action_collapse_all()

        def action_expand_all(self) -> None:
            for widget in self.query(Collapsible):
                if widget.display:
                    widget.collapsed = False

        def action_collapse_all(self) -> None:
            for widget in self.query(Collapsible):
                widget.collapsed = True

        def action_toggle_changes(self) -> None:
            checkbox = self.query_one('#changes', Checkbox)
            checkbox.value = not checkbox.value

    SnapshotAccordion().run()
