# Rule documentation

Each rule is documented for working embedded engineers: what actually goes
wrong in hardware, a minimal example, and how to fix it.

| Rule | Doc |
|---|---|
| PF001 Pin conflict | [PF001.md](../../src/preflight/rule_docs/PF001.md) |
| PF002 Clock / baud mismatch | [PF002.md](../../src/preflight/rule_docs/PF002.md) |
| PF003 Uninitialized peripheral use | [PF003.md](../../src/preflight/rule_docs/PF003.md) |
| PF004 NVIC / interrupt priority conflict | [PF004.md](../../src/preflight/rule_docs/PF004.md) |

The same text is available offline from the terminal: `preflight --explain PF001`.
The files live inside the package so they are installed with it.
