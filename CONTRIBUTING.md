# Contributing to Preflight

Thanks for helping. This guide assumes you have never seen the code.

## Ground rules

- **No network calls, no LLM calls.** Same input, same output, always.
- **No third-party runtime dependencies** (stdlib only; `pytest` for dev is fine).
- **Never guess.** If a rule lacks the data it needs, it returns `SKIPPED` with a
  reason. It never emits a placeholder finding.
- **Every finding cites a real location** (`Loc(file, line, key)`).

## Set up

```sh
git clone <your fork> && cd preflight
pip install -e ".[dev]"
pytest -q            # all green before you start
preflight --list-rules
```

## How the pieces fit

```
parsers (.ioc / .c / plugins)  ->  Config  ->  rules  ->  Findings  ->  text / JSON report
```

Both parsers produce the same `Config` (see `src/preflight/model.py`), so a rule
never knows or cares whether its input was a `.ioc` or a `.c` file. Rules only
read a `Config`; they never open files.

## Add a rule (5 steps)

A rule can live **in this repo** or in **your own pip package** (a plugin).
The code is identical; only where you register it differs.

**1. Implement the interface.** Subclass `Rule`:

```python
from preflight.findings import Finding, Loc, Severity
from preflight.model import Config
from preflight.rules.base import Applicability, Rule


class NoUnusedPins(Rule):
    id = "PF005"                       # unique; built-ins use PF001-PF004
    name = "Short human name"
    description = "One line: what this catches"
    docs = "Optional longer text shown by `preflight --explain PF005`."

    def applies_to(self, cfg: Config) -> Applicability:
        if not cfg.pins:
            return Applicability(False, "no pin assignments found")   # -> SKIPPED
        return Applicability(True)

    def check(self, cfg: Config) -> list[Finding]:
        findings = []
        for pin in cfg.pins:
            if <problem>:
                findings.append(Finding(
                    rule_id=self.id, severity=Severity.WARNING,
                    title="One line, under 70 characters",
                    detail="What is wrong, naming the actual values involved.",
                    loc=pin.loc,
                    evidence={"pin": pin.canonical},
                    remediation="A concrete next action.",
                ))
        return findings
```

`Config` holds `pins`, `clocks`, `peripherals`, `interrupts`, `mcu`, and (for `.c`
input) `code`. If your rule needs a CLI option, override
`from_options(cls, options)`; otherwise the default `cls()` is used.

**2. Register it.**
- *In this repo:* add the class to `BUILTIN_RULE_CLASSES` in
  `src/preflight/rules/registry.py`.
- *As a plugin package:* in **your** `pyproject.toml`:

  ```toml
  [project.entry-points."preflight.rules"]
  my_rule = "my_package.rules:NoUnusedPins"
  ```

  After `pip install`, `preflight --list-rules` shows it as `[plugin:my_package]`.
  A plugin that fails to import, isn't a `Rule`, or reuses an id is skipped with
  a warning; it never breaks the other rules.

**3. Add a fixture pair** under `tests/fixtures/` (real content, not stubs;
copy the shape of an existing fixture):
- `pf005_clean.ioc` (or `.c`): a realistic file the rule must **pass**.
- `pf005_broken_<mechanism>.ioc`: a realistic file that trips exactly one
  detection mechanism. One broken fixture per mechanism.

**4. Add tests** in `tests/test_rule_pf005.py`: clean passes, each broken
fixture yields the expected finding (rule id, severity, and the values in
`evidence`), and the `SKIPPED` path when the input doesn't apply.

**5. Document it** by adding `src/preflight/rule_docs/PF005.md` with the
sections `## What goes wrong`, `## Example`, `## How to fix` (see PF001.md).
`preflight --explain PF005` prints it. Plugins can use the `docs` attribute instead.

## Submitting

1. Branch from `main`, keep the change focused.
2. `pytest -q` must be green (CI runs it on Python 3.11 and 3.12).
3. Open a PR describing what the rule catches and why it's a real bug class.
4. If you ran Preflight on a real project, please log the result in
   `docs/findings/` (see its README), including false positives.

## Other contributions

- **Another MCU family:** see [docs/adding-mcu-support.md](docs/adding-mcu-support.md).
- **Better rule docs:** edit the files in `src/preflight/rule_docs/`.
- **Bug reports:** include the file (or a minimal excerpt), the command, and the output.
