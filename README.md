# Preflight

A static analyzer that catches STM32 firmware configuration bugs — pin conflicts, clock/baud
mismatches, uninitialized peripherals, and NVIC priority problems — before code gets flashed to
a board. Reads a CubeMX `.ioc` project file or a generated HAL `.c` file. Fully offline: no
network calls, no LLM calls, fully deterministic.

## Install

From the repo root:

```sh
pip install -e .
```

Requires Python 3.11+. No runtime dependencies. This installs a `preflight` command on your
`PATH` (via the console-script entry point), and also makes `python -m preflight` work as an
equivalent if `preflight` isn't found for some reason (e.g. a `PATH` issue).

Verify it installed:

```sh
preflight --version
```

## Try it right now

You don't need an STM32 project to try this — the repo ships with `.ioc` and `.c` fixtures
under `tests/fixtures/` that were built specifically to trip each rule, so you can see real
findings immediately.

**A pin conflict** (two different signals routed to the same physical pin):

```sh
preflight tests/fixtures/pf001_broken_dup_signal.ioc
```

```
preflight 0.1.0 — STM32F407VGTx (STM32F4) — pf001_broken_dup_signal.ioc

  PF001  Pin conflict .................................... FAIL  1 issue
  PF002  Clock / baud mismatch ........................... PASS
  PF003  Uninitialized peripheral use .................... SKIP  (PF003 analyses C source; input is a .ioc file)
  PF004  NVIC / interrupt priority conflict .............. SKIP  (no NVIC interrupt configuration found)

─── PF001  Pin conflict ────────────────────────────────────────────────────────

  ERROR  PA2 is assigned to two different signals
    tests\fixtures\pf001_broken_dup_signal.ioc:25  (PA2.Signal)
    Pin PA2 has conflicting assignments in this file: S_TIM2_CH3, USART2_TX. A physical pin can only
    carry one signal or alternate function at a time, so whichever assignment is applied last will
    silently override the other(s).
    → Remove or move one of these assignments so only one signal is routed to this pin.

1 error, 0 warnings across 4 rules.  2 rules run, 2 skipped.
```

Exit code is `1` (findings found). Try the clean counterpart and note it exits `0`:

```sh
preflight tests/fixtures/pf001_clean.ioc
```

**An uninitialized peripheral** (a HAL C file, not an `.ioc`) — `hspi1` is used but its
`MX_SPI1_Init()` call was deleted from `main()`:

```sh
preflight tests/fixtures/pf003_broken_never_init.c
```

```
preflight 0.1.0 — STM32F4 — pf003_broken_never_init.c

  PF001  Pin conflict .................................... PASS
  PF002  Clock / baud mismatch ........................... SKIP  (clock derivation not implemented for family 'STM32F4' and no declared peripheral clock frequencies were available)
  PF003  Uninitialized peripheral use .................... FAIL  1 issue
  PF004  NVIC / interrupt priority conflict .............. SKIP  (no NVIC interrupt configuration found)

─── PF003  Uninitialized peripheral use ────────────────────────────────────────

  ERROR  hspi1 is used but never initialized
    tests\fixtures\pf003_broken_never_init.c:17  (main)
    hspi1 is used in main() at line 17, but no HAL_*_Init call for it (directly or via a helper
    function) was found anywhere in this file. If the init lives in a different translation unit,
    this is a false positive -- PF003 analyses one file at a time.
    → Call the matching HAL_*_Init for hspi1 before this use.

1 error, 0 warnings across 4 rules.  2 rules run, 2 skipped.
```

PF002 shows `SKIP` here because this particular `.c` file's `SystemClock_Config` uses HSE but
the crystal frequency (`HSE_VALUE`) isn't `#define`d in this file (it normally lives in a
separate `stm32f4xx_hal_conf.h` the tool doesn't have). Supply it and PF002 turns on:

```sh
preflight tests/fixtures/pf003_broken_never_init.c --hse-hz 8000000
```

**More to try** — every fixture under `tests/fixtures/` targets a specific mechanism; the
`_broken_` ones fail, the `_clean_` ones pass:

```sh
preflight tests/fixtures/pf002_broken_baud_error.ioc      # baud rate off by >2% given the real PCLK1
preflight tests/fixtures/pf002_broken_unreachable.ioc     # baud rate literally unreachable from the clock
preflight tests/fixtures/pf004_broken_out_of_range.ioc    # NVIC priority out of range for the priority group
preflight tests/fixtures/pf004_broken_systick.ioc         # SysTick isn't the least-urgent interrupt
preflight tests/fixtures/pf001_broken_msp_af.c            # two MspInit functions claim the same pin
preflight tests/fixtures/pf004_broken_no_priority.c       # IRQ enabled without ever setting its priority
```

Add `--format json` to any of these to see the machine-readable form, or `-v` to also print
parser-level diagnostics (e.g. "N preprocessor conditionals not evaluated").

### Try it on your own project

```sh
preflight path/to/YourProject.ioc
```

or, for a generated HAL C file (typically `Core/Src/main.c` from a CubeMX/STM32CubeIDE project):

```sh
preflight path/to/main.c --mcu STM32F407VGTx --hse-hz 8000000
```

`--mcu` and `--hse-hz` are usually needed for `.c` input because a single `.c` file often can't
reveal the MCU family or the HSE crystal frequency on its own (see [Key options](#key-options)
below). An `.ioc` file always carries both, so it needs neither flag.

You can pass more than one file, or a glob pattern (quote it so your shell doesn't try to expand
it first — `preflight` expands globs itself, so this works identically on Windows, macOS and
Linux):

```sh
preflight Core/Src/main.c Core/Src/usart.c
preflight '**/*.ioc'
```

Every file is scanned and reported; the exit code is the worst across all of them.

Exits `0` if clean, `1` if findings at or above `--fail-on` (default: `warning`) were found, `2`
on a usage error, a path that doesn't exist, a glob that matched nothing, or unreadable/
unparseable input.

### Key options

- `--format {text,json}` — output format (default `text`)
- `--fail-on {info,warning,error,never}` — minimum severity that causes a non-zero exit
- `--rule PF001` (repeatable) — run only specific rules
- `--nvic-checks a,b1,b2,b3` — select PF004 sub-checks (default: all)
- `--baud-tolerance-pct` / `--baud-error-pct` — PF002 warning/error thresholds (default 1%/2%)
- `--mcu` / `--hse-hz` — supply MCU family / HSE crystal frequency when parsing a `.c` file that
  doesn't state them (a `.c` file alone often can't reveal the MCU family or an HSE value defined
  in a separate header)
- `--no-trust-declared-clocks` — disable the declared-frequency fallback for families whose PLL
  math isn't implemented (see below)
- `-v` / `--verbose` — also print parse-time diagnostics

## The four rules

| ID | Name | Reads |
|---|---|---|
| PF001 | Pin conflict | `.ioc` pin assignments, or `.c` `HAL_GPIO_Init` calls in MspInit functions |
| PF002 | Clock / baud mismatch | `.ioc` RCC/USART config, or `.c` `SystemClock_Config` + `UART_HandleTypeDef.Init` |
| PF003 | Uninitialized peripheral use | `.c` only — a `HAL_*_Transmit/Receive` call with no `HAL_*_Init` reachable before it |
| PF004 | NVIC / interrupt priority conflict | `.ioc` NVIC config, or `.c` `HAL_NVIC_*` calls |

All four rules always appear in the report, including ones that end up `SKIPPED` (with a reason)
because the input didn't have what that rule needed.

## CI/CD integration

### GitHub Action

```yaml
- uses: <owner>/preflight@v1
  with:
    path: '**/*.ioc'        # default; a file, a list, or a glob pattern
    fail-on: warning        # info | warning | error | never
```

Or, without the marketplace action, a raw workflow step:

```yaml
- uses: actions/setup-python@v5
  with: { python-version: '3.11' }
- run: pip install git+https://github.com/<owner>/preflight
- run: preflight '**/*.ioc' --fail-on warning
```

The Action does not scan only changed files — it scans everything matching `path` on every run.
This is deliberate: a changed-files-only mode needs `fetch-depth: 0` on your checkout step to
work at all, and silently scans *zero files* without it. A full scan of a few small `.ioc`/`.c`
files is fast enough that the tradeoff isn't worth that footgun.

### pre-commit

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/<owner>/preflight
    rev: v0.1.0
    hooks:
      - id: preflight        # scans staged .ioc files
      # - id: preflight-c     # opt-in: matches nothing until you set `files:`
      #   files: '^Core/Src/main\.c$'
```

`preflight-c` matches nothing by default on purpose — a naive `\.c$` pattern would scan every
vendor file under `Drivers/STM32F4xx_HAL_Driver/Src/`, which is slow and not your config. Point
`files:` at your own `main.c` (or wherever your inits live) to turn it on.

## JSON output

`--format json` emits a stable, versioned schema meant for scripting and CI tooling:

```json
{
  "schema_version": "1.0",
  "tool": { "name": "preflight", "version": "0.1.0" },
  "findings": [
    { "rule_id": "PF002", "rule_name": "Clock / baud mismatch", "severity": "error",
      "title": "...", "detail": "...", "location": { "file": "...", "line": 29, "key": "..." },
      "evidence": { "...": "..." }, "remediation": "..." }
  ],
  "files": [
    { "source": "blinky.ioc", "mcu": { "family": "STM32F4", "raw_name": "...", "core": "CM4" },
      "rules": [ { "rule_id": "PF001", "rule_name": "Pin conflict",
                   "status": "pass", "skip_reason": null, "finding_count": 0 } ] }
  ],
  "summary": { "files_scanned": 1, "errors": 1, "warnings": 0, "info": 0,
               "rules_run": 2, "rules_skipped": 2 }
}
```

`findings[]` is flat and self-contained — each entry carries its own `rule_id`, so
`jq '.findings[]'` works without walking a nested structure. `files[]` separately carries
per-rule PASS/FAIL/SKIPPED status per scanned file, since "this rule didn't apply to this file"
is different from "this rule passed", and a flat findings list has no place for it.

The field names are chosen so a future SARIF exporter is a rename, not a rewrite:

| Preflight JSON | SARIF 2.1.0 |
|---|---|
| `findings[].rule_id` | `runs[].results[].ruleId` |
| `findings[].severity` (`error`/`warning`/`info`) | `runs[].results[].level` (`error`/`warning`/`note`) |
| `findings[].title` + `detail` | `runs[].results[].message.text` |
| `findings[].location.file` / `.line` | `...locations[0].physicalLocation.artifactLocation.uri` / `...region.startLine` |
| `tool.name` / `tool.version` | `runs[].tool.driver.name` / `.version` |

`schema_version` follows semver-for-schemas: a breaking change bumps the major component.

## Known limitations

These are deliberate scope boundaries, not oversights — each is documented at the point in the
code where it matters:

- **Clock derivation only covers STM32F1 and STM32F4** from first principles. Other families
  fall back to the peripheral clock frequency CubeMX itself declared in the `.ioc`
  (`RCC.APB*Freq_Value`), which is usually correct but isn't independently verified — disable
  with `--no-trust-declared-clocks`.
- **PF001 rarely fires on a CubeMX-generated `.ioc`.** CubeMX's own UI prevents pin conflicts, so
  this mechanism mostly catches hand-edited or merged files. The `.c`-path check (two MspInit
  functions claiming the same pin via different alternate functions) is the one that fires on
  realistic generated code.
- **No pin remap-pair database.** A handful of packages let two different logical pin names share
  one physical pad; PF001 normalizes suffixes (`PC14-OSC32_IN` → `PC14`) but doesn't know about
  remap pairs.
- **PF003 treats control flow as a linear sequence and analyses one file at a time.** A
  conditional/loop-guarded init, an init that lives in a different translation unit, or a call
  through a function pointer can each produce a false positive — PF003 downgrades a flagged use
  inside a conditional/loop to a WARNING when an init for that handle exists elsewhere in the
  file, and always adds an INFO diagnostic (visible with `-v`) explaining this when it fires.
- **The `.c` parser is not a C compiler.** It uses a real character-scanner to strip comments and
  string literals safely, then regexes over the result — this is robust against the usual traps
  (comments, string literals, `#if 0` blocks) but doesn't understand macros, multi-file builds,
  or function-pointer indirection.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the project's ground rules and a worked walkthrough of
adding a new rule.

## Development

```sh
pip install -e ".[dev]"
pytest
```
