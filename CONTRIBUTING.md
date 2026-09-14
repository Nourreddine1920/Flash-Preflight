# Contributing to Preflight

## Project boundaries

These are non-negotiable, checked in review, not suggestions:

- **No network calls, no LLM calls.** Every finding must come from genuinely deterministic
  analysis of parsed data — same input, same output, forever.
- **No third-party runtime dependencies.** stdlib only. Dev-only tools (`pytest`) are fine.
- **No fabricated detection.** If a rule doesn't have the data it needs, it reports `SKIPPED`
  with a reason — it never guesses, and never emits a placeholder finding.
- **Every `Finding` cites a real `Loc(file, line, key)`.** No finding without a location a user
  can jump to.

## Adding a rule

The rule engine is designed so this is the main way to extend the project. Concretely:

1. **Subclass `Rule`** in a new `src/preflight/rules/<name>.py`:

   ```python
   from preflight.findings import Finding
   from preflight.model import Config
   from preflight.rules.base import Applicability, Rule

   class MyNewRule(Rule):
       id = "PF005"
       name = "Short human name"
       description = "One-line description of what this catches"

       def applies_to(self, cfg: Config) -> Applicability:
           if <required data absent>:
               return Applicability(False, "why this rule can't run on this input")
           return Applicability(True)

       def check(self, cfg: Config) -> list[Finding]:
           ...  # return a Finding for every real issue found; [] if clean
   ```

2. **Register it** in two places (yes, both — see [Known issue](#known-issue-duplicated-rule-registration) below):
   - append an instance to `ALL_RULES` in `src/preflight/rules/__init__.py`
   - construct it in `_build_rules()` in `src/preflight/cli.py`

3. **The contract your rule must follow:**
   - Consume only `Config` — never read files, never take a path. Both parsers
     (`.ioc` and `.c`) already normalize into this one shape so your rule works on either.
   - Return `Applicability(False, reason)` rather than running when the input lacks what you
     need. Never emit a finding based on a guess.
   - Every `Finding` needs a real `loc`, a plain-English `detail` that names the actual numbers
     involved (not "value mismatch detected" — say what the values are), and a `remediation`
     that's a concrete next action.

4. **Add fixtures.** Under `tests/fixtures/`, add at least one `pfNNN_clean.*` and one
   `pfNNN_broken_<mechanism>.*` per detection mechanism your rule implements — realistic content,
   not minimal stubs (look at the existing fixtures for the level of realism expected: real
   CubeMX `.ioc` key/value shapes, real HAL call patterns).

5. **Add `tests/test_rule_pf005.py`** exercising each mechanism against its fixture, plus the
   `SKIPPED` path when the input doesn't apply.

6. **Run `pytest`.** All existing tests must stay green — this is enforced in CI.

## Architecture at a glance

```
parsers/{ioc,cfile}.py  -->  Config  -->  rules/*.py  -->  RuleResult / Finding  -->  report/{text,jsonout}.py
```

Both parsers produce the same `Config` shape (see `model.py`), so every rule is source-agnostic:
it never knows or cares whether the input was a `.ioc` or a `.c` file.

- `clocks.py` — the only place clock-tree/baud-rate math lives. If your rule needs a derived
  frequency, call `clocks.solve()` / `clocks.compute_baud()` rather than reimplementing.
- `knowledge/` — static STM32 fact tables (family → core, bus placement, HAL function names).
  Extending family/peripheral coverage usually means adding here, not touching a rule.
- `parsers/clex.py` — the C lexer. If you need to scan `.c` source for a new pattern, use the
  already-stripped text it produces (comments and string literals are blanked) rather than
  regexing raw source, which will false-positive on the first commented-out example.

## Known issue: duplicated rule registration

`rules/__init__.py::ALL_RULES` and `cli.py::_build_rules()` both construct rule instances
separately — the latter exists because some rules take CLI-configured options
(`--baud-tolerance-pct`, `--nvic-checks`, etc.) that `ALL_RULES`'s default instances don't have.
Forgetting to update `cli.py` means your rule runs in tests but silently never runs from the
actual CLI. This is flagged as a known rough edge, not a deliberate design — a PR that collapses
both into one factory function is welcome.

## Testing

```sh
pip install -e ".[dev]"
pytest
```

148+ tests, no network access needed, runs in well under a second.
