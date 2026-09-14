"""PF003 - Uninitialized peripheral use.

A same-function "was Init called before this Transmit" check false-positives
on every real CubeMX project, because generated code calls a wrapper
(`MX_USART2_UART_Init()`) that calls `HAL_UART_Init()` one level down
(PLAN.md §8.1). This rule instead builds a small intra-file call graph and
resolves `initializes(F)` transitively: the set of handles that F, or
anything F calls, initializes.

Scope: only the entry point (`main`, or every locally-uncalled function when
`main` is absent -- e.g. IRQ handlers in a file with no `main`) is walked.
Control flow is treated as a linear textual sequence (PLAN.md §8.3) -- sound
for generated `main()`, an approximation everywhere else, which is why a use
inside a conditional/loop block is downgraded to WARNING rather than ERROR.
"""

from __future__ import annotations

from preflight.findings import Diagnostic, Finding, Loc, Severity
from preflight.model import CodeFacts, Config, Event, SourceKind
from preflight.rules.base import Applicability, Rule

_LIMITATIONS_NOTE = (
    "PF003 treats control flow as a linear sequence and analyses one file at "
    "a time: a conditional/loop-guarded init, an init in another translation "
    "unit, or a call through a function pointer can all produce a false "
    "positive here."
)


class UninitPeripheralRule(Rule):
    id = "PF003"
    name = "Uninitialized peripheral use"
    description = "A HAL <Peripheral>_Transmit/Receive call with no corresponding Init earlier in scope"

    def applies_to(self, cfg: Config) -> Applicability:
        if cfg.source_kind is not SourceKind.CFILE:
            return Applicability(False, "PF003 analyses C source; input is a .ioc file")
        if cfg.code is None or not cfg.code.functions:
            return Applicability(False, "no C function bodies could be parsed from this file")
        return Applicability(True)

    def check(self, cfg: Config) -> list[Finding]:
        code = cfg.code
        assert code is not None

        findings: list[Finding] = []
        seen: set[tuple[str, int]] = set()
        for root in self._roots(code):
            findings.extend(self._walk(cfg, code, root, seen))

        if findings:
            cfg.diagnostics.append(Diagnostic(level=Severity.INFO, message=_LIMITATIONS_NOTE))

        return findings

    def _roots(self, code: CodeFacts) -> list[str]:
        if "main" in code.functions:
            return ["main"]
        called: set[str] = set()
        for callees in code.call_graph.values():
            called.update(callees)
        return [name for name in code.functions if name not in called]

    def _initializes(
        self,
        code: CodeFacts,
        fn_name: str,
        memo: dict[str, set[str]],
        visiting: set[str],
    ) -> set[str]:
        if fn_name in memo:
            return memo[fn_name]
        if fn_name in visiting:
            return set()
        visiting.add(fn_name)

        result: set[str] = set()
        for event in code.events.get(fn_name, []):
            if event.kind == "init" and event.handle:
                result.add(event.handle)
            elif event.kind == "call" and event.callee and event.callee in code.functions:
                result |= self._initializes(code, event.callee, memo, visiting)

        visiting.discard(fn_name)
        memo[fn_name] = result
        return result

    def _walk(
        self, cfg: Config, code: CodeFacts, root: str, seen: set[tuple[str, int]]
    ) -> list[Finding]:
        memo: dict[str, set[str]] = {}
        # The full set of handles initialized anywhere reachable from this
        # root, computed once up front -- used only to word findings ("never
        # initialized" vs "used before init"), not to gate them: the walk
        # below still requires init to precede use, in file order.
        full_closure = self._initializes(code, root, memo, set())

        initialized: set[str] = set()
        findings: list[Finding] = []

        for event in code.events.get(root, []):
            if event.kind == "call" and event.callee and event.callee in code.functions:
                initialized |= self._initializes(code, event.callee, memo, set())
            elif event.kind == "deinit" and event.handle:
                initialized.discard(event.handle)
            elif event.kind == "init" and event.handle:
                initialized.add(event.handle)
            elif event.kind == "use" and event.handle:
                if event.handle in initialized:
                    continue
                key = (event.handle, event.offset)
                if key in seen:
                    continue
                seen.add(key)
                findings.append(self._finding_for_use(cfg, event, root, event.handle in full_closure))

        return findings

    def _finding_for_use(self, cfg: Config, event: Event, root: str, ever_init: bool) -> Finding:
        handle = event.handle
        assert handle is not None
        loc = Loc(file=cfg.source_path, line=event.line, key=root)
        in_conditional = event.brace_depth > 0

        if ever_init:
            title = f"{handle} is used before it is initialized"
            detail = (
                f"{handle} is used in {root}() at line {event.line}, but its "
                f"HAL_*_Init call (directly or via a helper function) is only "
                f"reached later, if at all, in this file's control flow."
            )
        else:
            title = f"{handle} is used but never initialized"
            detail = (
                f"{handle} is used in {root}() at line {event.line}, but no "
                f"HAL_*_Init call for it (directly or via a helper function) was "
                f"found anywhere in this file. If the init lives in a different "
                f"translation unit, this is a false positive -- PF003 analyses "
                f"one file at a time."
            )

        severity = Severity.ERROR
        if in_conditional and ever_init:
            severity = Severity.WARNING
            detail += (
                " This use is inside a conditional or loop body, and an init "
                "for this handle does exist elsewhere in the file, so this may "
                "be a false positive from PF003's linear control-flow "
                "approximation."
            )

        return Finding(
            rule_id=self.id,
            severity=severity,
            title=title,
            detail=detail,
            loc=loc,
            evidence={"handle": handle, "function": root, "line": event.line},
            remediation=f"Call the matching HAL_*_Init for {handle} before this use.",
        )
