# Real-bugs-found log

A transparent record of what Preflight found (or wrongly flagged) when run
against real open-source STM32 projects. **There are no entries yet.** Every
entry must come from an actual run; nothing here is illustrative.

## One file per entry
Name it `YYYY-MM-<project>-<short-slug>.md` (one file per entry means
contributors' pull requests never conflict). Copy `_template.md`.

## Required fields
A `key: value` block between `---` lines at the top of the file:

| Field | Meaning |
|---|---|
| `project` | Project name |
| `repo_url` | `https://...` link to the repository |
| `analyzed_commit` | Commit SHA that was scanned (7-40 hex chars), so the result is reproducible |
| `preflight_version` | Version that produced the result |
| `rule_id` | `PFxxx` |
| `verdict` | `confirmed-bug`, `false-positive` or `undetermined` |
| `summary` | One sentence: what was reported and what is actually true |
| `fix_url` | *(optional)* Link to the fix PR/issue, if one was made |

Below the block, add a few lines of detail: the command run, the finding, and
how you verified it by reading the code.

## Why false positives belong here
A log of only wins is marketing. False positives show where a rule needs to
improve, and they are welcome. Please report a `false-positive` as a normal
issue too so it can be fixed.

`tests/test_findings_log.py` checks that entries have the required fields.
