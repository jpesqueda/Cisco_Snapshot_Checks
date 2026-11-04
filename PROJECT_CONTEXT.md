# PROJECT CONTEXT — Cisco Snapshot Checks

- **Project:** Cisco IOS-XE Snapshot Collector + Smart Diff Engine
- **Current Version:** Prototype 1.1.0, version hidden in console banner
- **Environment:** Windows / PowerShell, Python 3.10+, Netmiko, Rich, NTC Templates/TextFSM, DeepDiff, PyYAML, Textual (TUI opcional)
- **Previous Version:** Cisco_Pre_Post_Checks.py V2.1 (PRE/POST, optional -b)
- **Architecture Change:** Numbered snapshots replace the mandatory PRE/POST binary. Legacy TXT capture import supported.
- **CLI:** `SnapshotChecks.py {collect,import,compare}`; `-h/--host`, `-hf/--host_file`, `-cf/--cmd`, `-u/--username`, `-p/--password`, `-b/--backup`, `-o/--output`, `-w/--workers`, `--snapshot`, `--from`, `--to`, `--rules`, `--expected-version`, `--tree`, `--tui`.
- **Files:** `Snapshots/<ID>/Checks`, `Snapshots/<ID>/JSON`, optional `Snapshots/<ID>/Backups`, `Reports/<FROM>_vs_<TO>`, `Logs/`.
- **Output:** JSON per snapshot, .diff/HTML/JSON per comparison, summary.csv; HTML acordeón FIELD/PRE/POST/STATUS, filtros y búsqueda, TUI opcional.
- **Safety:** read-only CLI commands, no configuration changes, TXT running-config stores secrets, compared model does not include configuration secrets.
- **Coverage:** partial. Explicit normalizers for version, interfaces, errors present, VLAN, BGP, IP route, port security, environment, STP root, trunk, etherchannel. Unmapped/unsupported commands are not validated.
- **Testing:** `python -m unittest discover -s tests -v`; 9 base tests plus accordion tests on legacy simulated captures. DeepDiff/NTC not installed in current build container (network package installation blocked); needs integration testing in real environment.
- **Next Steps:** confirm parser keys/NTC template support on production redacted captures, implement normalization for additional commands and health checks, validate DeepDiff behavior and SNMP/AAA/ACL semantic models.
