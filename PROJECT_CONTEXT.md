# PROJECT CONTEXT — Cisco Snapshot Checks

- **Project:** Cisco IOS-XE Snapshot Collector + Smart Diff Engine
- **Current Version:** Prototype 1.4.1, version hidden in console banner
- **Environment:** Windows / PowerShell, Python 3.10+, Netmiko, Rich, NTC Templates/TextFSM, DeepDiff, PyYAML, Textual (TUI opcional)
- **Previous Version:** Cisco_Pre_Post_Checks.py V2.1 (PRE/POST, optional -b)
- **Architecture Change:** Numbered snapshots replace the mandatory PRE/POST binary. Legacy TXT capture import supported.
- **CLI:** `SnapshotChecks.py {collect,import,compare}`; `-h/--host`, `-hf/--host_file`, `-cf/--cmd`, `-u/--username`, `-p/--password`, `-b/--backup`, `-o/--output`, `-w/--workers`, `--snapshot`, `--from`, `--to`, `--rules`, `--expected-version`, `--tree`, `--tui`.
- **Files:** `Snapshots/<ID>/Checks`, `Snapshots/<ID>/JSON`, optional `Snapshots/<ID>/Backups`, `Reports/<FROM>_vs_<TO>`, `Logs/`.
- **Output:** JSON per snapshot, .diff/HTML/JSON per comparison, summary.csv; HTML acordeón FIELD/PRE/POST/STATUS, filtros y búsqueda, TUI opcional.
- **Safety:** read-only CLI commands, no configuration changes, TXT running-config stores secrets, compared model does not include configuration secrets.
- **Coverage:** 42/43 commands NORMALIZED against the simulated PRE/POST; running-config excluded for security. Some dynamic fields are evidence-only and do not enter the comparison projection. Actual TextFSM/DeepDiff runtime still to be validated on Windows.
- **Testing:** `python -m unittest discover -s tests -v`; 32 test functions (including 22 normalizer subtests) plus accordion tests on legacy simulated captures. DeepDiff/NTC not installed in current build container (network package installation blocked); needs integration testing in real environment.
- **Next Steps:** confirm parser keys/NTC template support on production redacted captures, implement normalization for additional commands and health checks, validate DeepDiff behavior and SNMP/AAA/ACL semantic models.

## V1.2.0 changes
- Fallback automatic external TextFSM folder discovery, custom --templates-dir for collect/import.
- Exact command-to-template filename mapping or optional YAML/NTC index.
- PARSED_UNMAPPED and PARSE_ERROR keep coverage truthful; no automatic semantic diff of unmapped data.
- Original sample TXT, reports, Accordion and TUI retained.


## Update 1.3.0 — 2026-11-04
- Bundled 33 original custom TextFSM templates and index from user-supplied ZIP.
- CLI helper `TemplateAudit.py` for static candidate and runtime coverage reports.
- Fixed index handling to use textfsm.clitable and reject broad generic interface template matches.
- Added 7 internal semantic normalizers for inventory, switch, full interface state,
  switchport, PoE, DAI, and DHCP snooping, with narrow compared field allowlists.
- Preserves JSON parsed records of unmapped commands, up to 5000 records each.
- Tested: 24 local unittest tests; 20 / 43 built-in-normalized in simulated captures;
  actual external TextFSM parsing not tested due dependency unavailability.

## Update 1.4.0 — 2026-11-04
- 22 additional semantic normalizers in `snapshotchecks/pending_normalizers.py`.
- Existing 33 TextFSM templates/index preserved without changes.
- Added selectively compared fields in compare_rules.yaml; dynamic data excluded.
- 42/43 commands normalize in both provided sample captures; show running-config stays SKIPPED_SENSITIVE.
- Offline tests: 32 passed, plus 26 subtest cases. Actual external TextFSM/DeepDiff libraries could not be installed in the build environment.
- Operational diff remains INCOMPLETE until running-config policy is decided or coverage policy is refined.

## Update 1.4.1
- Added environmental sensor and alarm tables, link-state inference from explicit timer columns, and one explicit no-authentication-sessions response.
- Re-import both source TXT captures before comparing; this release does not change raw captures or coverage for other commands.
- 38 offline tests passed with reconstructed fixtures and the existing simulations.
