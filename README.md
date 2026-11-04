# Cisco Snapshot Checks — Versión 1.2.0 — Accordion + External TextFSM

Comparador estructurado de capturas Cisco IOS-XE, basado en snapshots numerados. **Nunca cambia configuraciones de red**; SSH se utiliza únicamente para comandos `show`. Compatible con Windows y Python 3.10+.

## Instalación

```powershell
python -m pip install -r requirements.txt
python -c "import ntc_templates, textfsm, deepdiff, netmiko, rich, yaml, textual; print('Dependencies OK')"
```

El modo `import` y algunos parsers locales también funcionan sin NTC/Netmiko; si falta DeepDiff, el comparador informa que utilizó un fallback de Python. Para utilizar todo el motor recomendado, instala las dependencias. **No hace falta openpyxl:** el resumen se guarda en CSV.

## 1. Probar sin conectarte a switches

Se incluyen capturas simuladas del mismo Catalyst C9300 antes (17.5.5) y después (17.5.6) de un upgrade.

```powershell
python SnapshotChecks.py import -f examples/C9300-ACCESS-01_PRE_SIMULATED.txt --snapshot 001 -o Upgrade_Test
python SnapshotChecks.py import -f examples/C9300-ACCESS-01_POST_SIMULATED.txt --snapshot 002 -o Upgrade_Test
python SnapshotChecks.py compare --from 001 --to 002 -o Upgrade_Test --expected-version 17.5.6 --tree
python SnapshotChecks.py compare --from 001 --to 002 -o Upgrade_Test --expected-version 17.5.6 --tui
```

Resultado previsto de **las comprobaciones realmente implementadas**:

```
C9300-ACCESS-01  INCOMPLETE
C9300-ACCESS-01  [INCOMPLETE]
├── EXPECTED  system
├── PASS      hardware
├── PASS      interfaces
├── PASS      vlans
├── PASS      routing
├── PASS      layer2
└── PASS      security
```

`INCOMPLETE` es intencional: algunos comandos aún no se evalúan semánticamente y `running-config` se excluye de JSON para no duplicar secretos. `PASS` en una sección significa **solo que los campos evaluados no cambiaron**, no que todos los protocolos estén saludables.

## 2. Capturar snapshots reales

Ejecuta desde la carpeta del proyecto. Sin argumentos, el script solicita host/host file, comandos, usuario y contraseña, y asigna el siguiente snapshot numérico automáticamente.

```powershell
python SnapshotChecks.py
```

O con CLI:

```powershell
python SnapshotChecks.py collect -hf hosts.txt -cf cmd.txt -u admin -o Upgrade_Cat9k --snapshot 001 -b
python SnapshotChecks.py collect -hf hosts.txt -cf cmd.txt -u admin -o Upgrade_Cat9k --snapshot 002 -b
python SnapshotChecks.py compare --from 001 --to 002 -o Upgrade_Cat9k --expected-version 17.5.6
```

Para ejecutar sobre un equipo: `collect -h SW01 -u admin`. La contraseña se solicita sin eco cuando omites `-p`. Workers=20 por defecto, configurable con `-w`. Repetir un snapshot con archivos existentes requiere confirmación de sobrescritura; el script no borra datos de otros dispositivos. Los logs detallan errores por dispositivo.

## 3. Carpetas de salida

```
Upgrade_Cat9k/
├── Snapshots/
│   ├── 001/
│   │   ├── Checks/SW01.txt
│   │   ├── JSON/SW01.json
│   │   └── Backups/SW01_Running_Config.txt  (solo con -b)
│   ├── 002/
│   │   ├── Checks/SW01.txt
│   │   ├── JSON/SW01.json
│   │   └── Backups/SW01_Running_Config.txt
│   └── 003/... (opcional)
├── Reports/
│   └── 001_vs_002/
│       ├── SW01.diff
│       ├── SW01.json
│       ├── SW01.html
│       └── summary.csv
└── Logs/
```

Cualquier par se puede comparar: `001` vs `002`, `001` vs `003` o `002` vs `003`. Si falta un equipo en un snapshot, se registra en `missing_devices.txt` y el proceso termina con código distinto de cero.

## 4. Arquitectura

1. `snapshotchecks/parsing.py`: divide las capturas por `COMMAND:`, llama a NTC Templates (`parse_output(platform='cisco_ios', ...)`) y, cuando no funciona, intenta una plantilla local TextFSM o el parser interno explícito.
2. `NORMALIZERS` traduce comandos distintos a un modelo estable: `system`, `hardware`, `interfaces`, `vlans`, `routing`, `layer2`, `security`.
3. `compare_rules.yaml` especifica una **allowlist** de campos por sección. Los contadores de bytes/paquetes, edades, uptime y BGP MsgRcvd/MsgSent no se comparan.
4. `snapshotchecks/comparison.py`: DeepDiff compara el modelo filtrado de cada sección, no el JSON completo. Un cambio de versión coincidente con `--expected-version` se clasifica `EXPECTED`.
5. `snapshotchecks/comparison.py`: además de los cambios DeepDiff, crea **filas semánticas por campo** `FIELD | PRE | POST | STATUS` para comparar tanto cambios como valores sin cambios. No compara los campos dinámicos fuera de la allowlist.
6. `snapshotchecks/html_report.py`: genera HTML autónomo con secciones `<details>` colapsables, tablas, **Expand all / Collapse all**, **Changes only** y búsqueda por campo. JavaScript local sin CDN ni conexiones externas.
7. `snapshotchecks/tui.py`: visor opcional de Textual con `Collapsible` + `DataTable`, selector de equipo y filtro **Changes only**; activar con `--tui` en PowerShell o Windows Terminal. `--tree` sigue usando Rich Tree."

### Extensión de templates

- Primero verifica si NTC Templates ya soporta el comando.
- Si falta, agrega un template TextFSM en `custom_templates/` y una entrada de comando/plataforma en `custom_templates/index.yaml`.
- Para **compararlo semánticamente**, agrega también un normalizador para los campos relevantes y registra el comando en `NORMALIZERS` en `snapshotchecks/parsing.py`.
- Define los campos de comparación en `compare_rules.yaml` únicamente cuando amplíes el modelo. Agregar/quitar un comando de `cmd.txt` **no exige editar el YAML** si su normalizador ya existe.
- Un template que parsea pero no se normaliza aparecerá como `PARSED_UNMAPPED` y **no contará como PASS**.

### Reglas actuales

- IOS-XE version; estado, descripción y VLAN de interfaces; IP/protocol; presencia de errores (no contador absoluto); VLAN; BGP neighbors y prefijos; rutas; port-security (máximo y acción, no MACs aprendidas); estado ambiental; STP roots; trunks y EtherChannels (según parser/formato).
- Los comandos restantes se reportan `UNSUPPORTED`, `PARSED_UNMAPPED` o `PARSE_ERROR` cuando corresponda. La cobertura depende de formato IOS-XE y templates instalados.
- `show running-config` se conserva solo en el TXT original y los backups autorizados; este prototipo **no compara todavía cambios de configuración global** (AAA, ACL, SNMPv3, etc.).

## 5. Seguridad / pruebas en producción

- Solo comandos `show`; no `config t` y no `write memory`.
- El texto RAW y los backups de `running-config` pueden contener passwords, keys, hashes, comunidades SNMP y datos operativos sensibles: almacena el directorio con permisos restringidos. No compartas TXT de producción sin redactar datos.
- Primero usa `import` con capturas reales y revisa `coverage` de cada JSON; realiza un piloto con un switch antes de habilitar muchos workers.
- No interpretes `INCOMPLETE` como salud validada ni `PASS` como chequeo completo. El algoritmo es una comparación de estados, **no un health check independiente**.
- Usa un usuario con permisos de solo lectura y confirma que el comando `show running-config` esté autorizado.
- Capturas incompletas, errores o comandos distintos se listan en `coverage`, no se convierten silenciosamente en PASS.

## 6. Pruebas

```powershell
python -m unittest discover -s tests -v
```

Casos incluidos: upgrade esperado, BGP Idle, VLAN suspendida, interfaz caída, comando faltante, sanitización de JSON, HTML acordeón con tablas, protección de HTML y numeración de snapshots.

## 7. Códigos de salida

- `0`: captura exitosa o comparación completa sin cambios relevantes.
- `1`: fallas de captura, regresiones detectadas o dispositivos faltantes.
- `2`: argumentos/archivos inválidos o error operativo.
- `3`: comparación sin regresiones encontradas, pero con cobertura incompleta.

**Limitación de validación:** esta entrega incluye pruebas automatizadas locales de la ruta de parsers internos. En este entorno no fue posible instalar NTC Templates ni DeepDiff por falta de acceso a paquetes, por lo que su integración en un entorno Windows con las librerías reales debe validarse en tu laboratorio antes de aplicarla de forma general en producción.


## 8. Nuevo reporte expandible (1.1.0)

Cada sección (SYSTEM, HARDWARE, INTERFACES, VLANS, ROUTING, LAYER2, SECURITY) presenta las columnas `FIELD | PRE | POST | STATUS`.

- `PASS`: el campo seleccionado sigue igual.
- `EXPECTED`: por ejemplo, cambio IOS-XE a la versión esperada.
- `CHANGE`: diferencia no prevista que debe revisarse (NO es automáticamente un fallo).
- `ERROR`: se detectó una condición incorrecta, como versión distinta a la esperada.
- `NOT_EVALUATED`, `MISSING`, `INCOMPLETE`: cobertura insuficiente, nunca PASS.

El HTML abre automáticamente secciones con cambios, usa `Changes only` para ocultar filas PASS,
permite expandir/contraer todas las secciones y buscar puertos. Abre el archivo `.html` en Edge/Chrome
sin servidor. El visor Textual abre las mismas tablas en PowerShell mediante `--tui`; se navega
con flechas, `Enter`, botones o `E` (expand), `C` (collapse), `F` (filter), `Q` (quit).

**Nota:** los datos etiquetados PRE/POST en la tabla son los snapshots que selecciones,
no dos modos fijos de recolección. `001 vs 003` también funciona. Comandos no evaluados
siguen enumerados en Command Coverage y mantienen resultado global INCOMPLETE.

**Limitación de pruebas:** HTML, proyecciones, regresiones y CLI se validaron localmente;
la TUI no pudo ejecutarse aquí porque el entorno no dispone de Textual y no permite
instalar paquetes. La API usada se basa en la documentación oficial y debe verificarse
inicialmente en Windows antes de depender de ella durante un mantenimiento real.


## 9. Integrar la carpeta `ntc_templates_cisco_ios` (1.2.0)

El motor ahora admite un directorio completo de templates `.textfsm`, **sin exigir que
crees una entrada YAML por cada archivo**. Las plantillas propias se ejecutan como
fallback cuando NTC Templates instalado no logra parsear la salida.

**Opción A — autodetección:** copia tu carpeta `ntc_templates_cisco_ios/` a la misma
ubicación que `SnapshotChecks.py`:

```text
Cisco_Snapshot_Checks/
├── SnapshotChecks.py
├── ntc_templates_cisco_ios/
│   ├── cisco_ios_show_clock.textfsm
│   ├── cisco_ios_show_ip_arp.textfsm
│   └── ...
├── snapshotchecks/
└── ...
```

**Opción B — carpeta externa en Windows:** evita copiar los templates.

```powershell
python SnapshotChecks.py import -f examples/C9300-ACCESS-01_PRE_SIMULATED.txt --snapshot 001 -o Upgrade_Test --templates-dir "C:\Automation\Cisco_Command_Parser\ntc_templates_cisco_ios"
python SnapshotChecks.py import -f examples/C9300-ACCESS-01_POST_SIMULATED.txt --snapshot 002 -o Upgrade_Test --templates-dir "C:\Automation\Cisco_Command_Parser\ntc_templates_cisco_ios"
python SnapshotChecks.py compare --from 001 --to 002 -o Upgrade_Test --expected-version 17.5.6
```

En `collect` puedes pasar también `--templates-dir`; las sesiones SSH y los
archivos TXT no cambian. **Para snapshots ya importados, vuelve a ejecutar
`import` de sus TXT originales** y confirma la sobrescritura, porque `compare`
utiliza el JSON guardado, no vuelve a parsear automáticamente.

**Orden de parsing:** NTC Templates empaquetado → carpeta externa →
`custom_templates/` del proyecto → parser propio para comandos con normalizador.
La carpeta externa puede tener un `index` NTC estándar, un `index.yaml`
con mapeos por plataforma y comando, o **solo nombres**
`cisco_ios_show_....textfsm`. Solo se buscan nombres exactos y un pequeño
conjunto de alias IOS-XE equivalentes; no se asume que `show switch` sea igual
a `show switch detail`.

**Cobertura:**

- `NORMALIZED`: salida parseada y mapeada a campos comparables.
- `PARSED_UNMAPPED`: TextFSM extrajo registros; todavía falta normalizador
  en `snapshotchecks/parsing.py` y regla si la sección es nueva.
- `UNSUPPORTED`: no se halló un parser que reconociera esa salida.
- `PARSE_ERROR`: se identificó una plantilla pero hubo error o no coincidió.
- `SKIPPED_SENSITIVE`: `show running-config` sigue fuera del JSON.

Los templates de tu captura **no están incluidos en este ZIP** porque recibimos
solo una imagen, no los archivos `.textfsm`. Al copiar tu carpeta real, la
cobertura aumentará solo para los formatos que esos templates reconozcan.
Tener template no significa que el campo se compare ni garantiza un PASS.

Una prueba rápida:

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python SnapshotChecks.py import -f examples/C9300-ACCESS-01_PRE_SIMULATED.txt --snapshot 001 -o Upgrade_Test --templates-dir ntc_templates_cisco_ios
```

Revisa `Upgrade_Test/Snapshots/001/JSON/C9300-ACCESS-01.json` bajo `coverage`.
Por ejemplo, `show clock` podrá reportar `PARSED_UNMAPPED` aunque siga fuera de
las comparaciones, mientras `show interfaces counters errors` podrá ser `NORMALIZED`
si el template devuelve los campos esperados.
