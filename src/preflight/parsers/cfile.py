"""Turn a generated HAL `.c` file into a source-agnostic `Config` (PLAN.md §2.4).

Runs on `clex.strip_and_index()` output throughout, so every regex here is
already safe from comments and string literals. Two kinds of scans are used:

  - Global scans (handle declarations, `.Instance =`, RCC clock struct
    fields, NVIC calls): these patterns are conventionally unique per file in
    CubeMX-generated code, so scanning the whole file is simple and correct.

  - Per-function scans (GPIO pin simulation, call graph, init/use events):
    these need order and function-scoping, so they walk each
    `clex.CFunction` body independently.
"""

from __future__ import annotations

import re
from pathlib import Path

from preflight.findings import Diagnostic, Loc, Severity
from preflight.knowledge.families import (
    CORE_IRQNS,
    core_for_family,
    family_from_header_include,
    hsi_hz_for_family,
    nvic_prio_bits_for_family,
)
from preflight.knowledge.hal_api import classify_call
from preflight.knowledge.usart_ip import usart_ip_for_family
from preflight.model import (
    CFunction,
    ClockTree,
    CodeFacts,
    Config,
    Event,
    HandleDecl,
    Interrupt,
    McuInfo,
    NvicEvent,
    Peripheral,
    PinAssignment,
    PllConfig,
    SourceKind,
)
from preflight.parsers.clex import split_functions, strip_and_index

_HANDLE_DECL_RE = re.compile(r"\b(?P<kind>[A-Za-z0-9]+)_HandleTypeDef\s+(?P<name>\w+)\s*;")
_FIELD_ASSIGN_RE = re.compile(r"\b(?P<var>\w+)\.(?P<field>[\w.]+)\s*=\s*(?P<value>[^;]+);")
_GPIO_FIELD_RE = re.compile(r"\b(?P<struct>\w+)\.(?P<field>Pin|Mode|Pull|Speed|Alternate)\s*=\s*(?P<value>[^;]+);")
_HAL_GPIO_INIT_RE = re.compile(r"\bHAL_GPIO_Init\s*\(\s*(?P<port>GPIO[A-Z])\s*,\s*&\s*(?P<struct>\w+)\s*\)")
_CALL_RE = re.compile(r"\b(?P<name>[A-Za-z_]\w*)\s*\(")
_HANDLE_ARG_RE = re.compile(r"\s*&?\s*(?P<handle>\w+)")
_NVIC_SET_PRIORITY_RE = re.compile(
    r"\bHAL_NVIC_SetPriority\s*\(\s*(?P<irqn>\w+_IRQn)\s*,\s*(?P<preempt>[^,()]+),\s*(?P<sub>[^)]+)\)"
)
_NVIC_ENABLE_RE = re.compile(r"\bHAL_NVIC_EnableIRQ\s*\(\s*(?P<irqn>\w+_IRQn)\s*\)")
_NVIC_GROUPING_RE = re.compile(r"\bHAL_NVIC_SetPriorityGrouping\s*\(\s*(?P<group>NVIC_PRIORITYGROUP_\d)\s*\)")
_HSE_DEFINE_RE = re.compile(
    r"#define\s+HSE_VALUE\s+\(*\s*(?:\([A-Za-z_]\w*\)\s*)?(?P<value>\d+)U?\s*\)*"
)
_GPIO_PIN_BIT_RE = re.compile(r"GPIO_PIN_(\d{1,2})\b")
_TRAILING_INT_RE = re.compile(r"(\d+)\s*$")
_PERIPH_NAME_RE = re.compile(r"^(?P<kind>[A-Za-z]+)(?P<num>\d*)$")

_CONTROL_KEYWORDS = {
    "if",
    "for",
    "while",
    "switch",
    "return",
    "sizeof",
    "do",
    "else",
}


def parse_cfile(
    path: str | Path, *, mcu_override: str | None = None, hse_hz_override: int | None = None
) -> Config:
    filename = str(path)
    src = Path(path).read_text(encoding="utf-8", errors="replace")
    stripped = strip_and_index(src)
    text = stripped.stripped
    diagnostics: list[Diagnostic] = []

    if stripped.conditionals_not_evaluated:
        diagnostics.append(
            Diagnostic(
                level=Severity.INFO,
                message=(
                    f"{stripped.conditionals_not_evaluated} preprocessor conditional(s) "
                    f"not evaluated; analysis assumes all branches are live"
                ),
            )
        )

    family = mcu_override or family_from_header_include(src)
    if family is None:
        diagnostics.append(
            Diagnostic(
                level=Severity.INFO,
                message="could not determine MCU family from #include; pass --mcu to enable clock/NVIC checks",
            )
        )
    mcu = McuInfo(
        raw_name=family,
        family=family,
        core=core_for_family(family),
        nvic_prio_bits=nvic_prio_bits_for_family(family),
        hsi_hz=hsi_hz_for_family(family),
        usart_ip=usart_ip_for_family(family),
    )

    handles = _parse_handles(text, filename)
    field_values = _parse_field_assignments(text, filename)
    peripherals = _parse_peripherals(handles, field_values)
    clocks = _parse_clocks(src, field_values, family, hse_hz_override)

    functions = split_functions(stripped)
    func_dict = {f.name: f for f in functions}
    pins = _parse_gpio_pins(text, filename, func_dict)
    call_graph, events = _parse_call_graph_and_events(text, filename, func_dict, handles)

    nvic_set, nvic_enable, priority_grouping = _parse_nvic_calls(text, filename)
    interrupts = _build_interrupts(nvic_set, nvic_enable)

    code = CodeFacts(
        functions=func_dict,
        call_graph=call_graph,
        handles=handles,
        events=events,
        nvic_set=nvic_set,
        nvic_enable=nvic_enable,
        priority_grouping=priority_grouping,
        entry_point="main" if "main" in func_dict else None,
    )

    return Config(
        source_path=filename,
        source_kind=SourceKind.CFILE,
        mcu=mcu,
        pins=pins,
        clocks=clocks,
        peripherals=peripherals,
        interrupts=interrupts,
        priority_group=priority_grouping,
        code=code,
        raw=None,
        diagnostics=diagnostics,
    )


def _parse_handles(text: str, filename: str) -> dict[str, HandleDecl]:
    handles: dict[str, HandleDecl] = {}
    for m in _HANDLE_DECL_RE.finditer(text):
        name = m.group("name")
        kind = m.group("kind").upper()
        line = text.count("\n", 0, m.start()) + 1
        handles[name] = HandleDecl(name=name, kind=kind, loc=Loc(file=filename, line=line, key=name))
    return handles


def _parse_field_assignments(text: str, filename: str) -> dict[tuple[str, str], tuple[str, Loc]]:
    values: dict[tuple[str, str], tuple[str, Loc]] = {}
    for m in _FIELD_ASSIGN_RE.finditer(text):
        var, field, value = m.group("var"), m.group("field"), m.group("value").strip()
        line = text.count("\n", 0, m.start()) + 1
        values[(var, field)] = (value, Loc(file=filename, line=line, key=f"{var}.{field}"))
    return values


def _div_from_enum(value: str | None) -> int | None:
    if value is None:
        return None
    m = _TRAILING_INT_RE.search(value)
    return int(m.group(1)) if m else None


def _parse_peripherals(
    handles: dict[str, HandleDecl], field_values: dict[tuple[str, str], tuple[str, Loc]]
) -> dict[str, Peripheral]:
    peripherals: dict[str, Peripheral] = {}
    for handle_name in handles:
        instance = field_values.get((handle_name, "Instance"))
        if instance is None:
            continue
        periph_name = instance[0]
        m = _PERIPH_NAME_RE.match(periph_name)
        kind = m.group("kind") if m else periph_name
        instance_num = int(m.group("num")) if m and m.group("num") else 0

        params: dict[str, str] = {}
        locs: dict[str, Loc] = {}
        prefix = "Init."
        for (var, field), (value, loc) in field_values.items():
            if var == handle_name and field.startswith(prefix):
                short_field = field[len(prefix) :]
                params[short_field] = value
                locs[short_field] = loc

        peripherals[periph_name] = Peripheral(
            name=periph_name, kind=kind, instance=instance_num, params=params, locs=locs
        )
    return peripherals


def _parse_clocks(
    src: str,
    field_values: dict[tuple[str, str], tuple[str, Loc]],
    family: str | None,
    hse_hz_override: int | None,
) -> ClockTree:
    hse_hz = hse_hz_override
    if hse_hz is None:
        m = _HSE_DEFINE_RE.search(src)
        if m:
            hse_hz = int(m.group("value"))

    def field(var: str, name: str) -> str | None:
        entry = field_values.get((var, name))
        return entry[0] if entry else None

    sysclk_src_raw = field("RCC_ClkInitStruct", "SYSCLKSource")
    sysclk_source = None
    if sysclk_src_raw:
        if "PLLCLK" in sysclk_src_raw:
            sysclk_source = "PLLCLK"
        elif "HSE" in sysclk_src_raw:
            sysclk_source = "HSE"
        elif "HSI" in sysclk_src_raw:
            sysclk_source = "HSI"

    ahb_div = _div_from_enum(field("RCC_ClkInitStruct", "AHBCLKDivider")) or 1
    apb1_div = _div_from_enum(field("RCC_ClkInitStruct", "APB1CLKDivider")) or 1
    apb2_div = _div_from_enum(field("RCC_ClkInitStruct", "APB2CLKDivider")) or 1

    pll_source_raw = field("RCC_OscInitStruct", "PLL.PLLSource")
    if family == "STM32F4":
        source = "HSE" if pll_source_raw and "HSE" in pll_source_raw else ("HSI" if pll_source_raw else None)
        pll = PllConfig(
            source=source,
            m=_int_or_none(field("RCC_OscInitStruct", "PLL.PLLM")),
            n=_int_or_none(field("RCC_OscInitStruct", "PLL.PLLN")),
            p=_div_from_enum(field("RCC_OscInitStruct", "PLL.PLLP")),
            q=_int_or_none(field("RCC_OscInitStruct", "PLL.PLLQ")),
        )
    elif family == "STM32F1":
        prediv = None
        if pll_source_raw and "HSI" in pll_source_raw:
            source = "HSI_DIV2"
        elif pll_source_raw and "HSE" in pll_source_raw:
            source = "HSE"
            prediv_raw = field("RCC_OscInitStruct", "PLL.PREDIV1")
            prediv = 2 if prediv_raw and "DIV2" in prediv_raw else 1
        else:
            source = None
        pll = PllConfig(source=source, mul=_div_from_enum(field("RCC_OscInitStruct", "PLL.PLLMUL")), prediv=prediv)
    else:
        pll = PllConfig()

    return ClockTree(
        hse_hz=hse_hz,
        pll=pll,
        sysclk_source=sysclk_source,
        ahb_div=ahb_div,
        apb1_div=apb1_div,
        apb2_div=apb2_div,
    )


def _int_or_none(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _expand_gpio_pins(value: str) -> list[int]:
    if "GPIO_PIN_All" in value:
        return list(range(16))
    return [int(n) for n in _GPIO_PIN_BIT_RE.findall(value)]


def _parse_gpio_pins(
    text: str, filename: str, functions: dict[str, CFunction]
) -> list[PinAssignment]:
    pins: list[PinAssignment] = []

    for fn_name, fn in functions.items():
        body = text[fn.body_start : fn.body_end]
        events: list[tuple[int, str, re.Match]] = []
        for m in _GPIO_FIELD_RE.finditer(body):
            events.append((m.start(), "assign", m))
        for m in _HAL_GPIO_INIT_RE.finditer(body):
            events.append((m.start(), "init", m))
        events.sort(key=lambda e: e[0])

        state: dict[str, dict[str, tuple[str, int]]] = {}
        for offset, kind, m in events:
            abs_offset = fn.body_start + offset
            line = text.count("\n", 0, abs_offset) + 1
            if kind == "assign":
                struct, field, value = m.group("struct"), m.group("field"), m.group("value").strip()
                state.setdefault(struct, {})[field] = (value, line)
            else:
                port_letter = m.group("port")[-1]
                struct = m.group("struct")
                fields = state.get(struct, {})
                pin_value = fields.get("Pin")
                if pin_value is None:
                    continue
                mode = fields.get("Mode", (None, None))[0]
                alternate = fields.get("Alternate", (None, None))[0]
                for pin_num in _expand_gpio_pins(pin_value[0]):
                    pins.append(
                        PinAssignment(
                            raw_name=f"P{port_letter}{pin_num}",
                            port=port_letter,
                            number=pin_num,
                            signal=None,
                            mode=mode,
                            label=None,
                            alternate=alternate,
                            owner=fn_name,
                            loc=Loc(file=filename, line=line, key=fn_name),
                        )
                    )
    return pins


def _parse_call_graph_and_events(
    text: str,
    filename: str,
    functions: dict[str, CFunction],
    handles: dict[str, HandleDecl],
) -> tuple[dict[str, list[str]], dict[str, list[Event]]]:
    call_graph: dict[str, list[str]] = {}
    events: dict[str, list[Event]] = {}

    for fn_name, fn in functions.items():
        body = text[fn.body_start : fn.body_end]
        depths = _brace_depths(body)
        fn_events: list[Event] = []
        callees: list[str] = []

        for m in _CALL_RE.finditer(body):
            name = m.group("name")
            if name in _CONTROL_KEYWORDS:
                continue
            offset = m.start()
            abs_offset = fn.body_start + offset
            line = text.count("\n", 0, abs_offset) + 1
            depth = depths[offset]

            if name in functions and name != fn_name:
                callees.append(name)
                fn_events.append(
                    Event(kind="call", handle=None, callee=name, offset=abs_offset, line=line, fn_name=fn_name, brace_depth=depth)
                )
                continue

            kind = classify_call(name)
            if kind is None:
                continue

            arg_match = _HANDLE_ARG_RE.match(body, m.end())
            handle = arg_match.group("handle") if arg_match else None
            if handle not in handles:
                continue

            fn_events.append(
                Event(kind=kind, handle=handle, callee=None, offset=abs_offset, line=line, fn_name=fn_name, brace_depth=depth)
            )

        call_graph[fn_name] = callees
        events[fn_name] = fn_events

    return call_graph, events


def _brace_depths(body: str) -> list[int]:
    depths = [0] * (len(body) + 1)
    running = 0
    for idx, ch in enumerate(body):
        depths[idx] = running
        if ch == "{":
            running += 1
        elif ch == "}":
            running -= 1
    depths[len(body)] = running
    return depths


def _parse_nvic_calls(text: str, filename: str) -> tuple[list[NvicEvent], list[NvicEvent], str | None]:
    nvic_set: list[NvicEvent] = []
    nvic_enable: list[NvicEvent] = []
    priority_grouping: str | None = None

    for m in _NVIC_SET_PRIORITY_RE.finditer(text):
        line = text.count("\n", 0, m.start()) + 1
        preempt = _int_or_none(m.group("preempt").strip())
        sub = _int_or_none(m.group("sub").strip())
        nvic_set.append(
            NvicEvent(
                irqn=m.group("irqn"),
                kind="set_priority",
                preempt=preempt,
                sub=sub,
                loc=Loc(file=filename, line=line),
            )
        )

    for m in _NVIC_ENABLE_RE.finditer(text):
        line = text.count("\n", 0, m.start()) + 1
        nvic_enable.append(
            NvicEvent(irqn=m.group("irqn"), kind="enable", preempt=None, sub=None, loc=Loc(file=filename, line=line))
        )

    grouping_matches = list(_NVIC_GROUPING_RE.finditer(text))
    if grouping_matches:
        priority_grouping = grouping_matches[-1].group("group")

    return nvic_set, nvic_enable, priority_grouping


def _build_interrupts(nvic_set: list[NvicEvent], nvic_enable: list[NvicEvent]) -> dict[str, Interrupt]:
    interrupts: dict[str, Interrupt] = {}
    enabled_irqns = {e.irqn for e in nvic_enable}
    enable_loc = {e.irqn: e.loc for e in nvic_enable}

    last_set: dict[str, NvicEvent] = {}
    for e in nvic_set:
        last_set[e.irqn] = e

    all_irqns = set(last_set) | enabled_irqns
    for irqn in all_irqns:
        set_event = last_set.get(irqn)
        loc = enable_loc.get(irqn) or (set_event.loc if set_event else Loc(file="<unknown>", line=0))
        interrupts[irqn] = Interrupt(
            irqn=irqn,
            enabled=irqn in enabled_irqns,
            preempt=set_event.preempt if set_event else None,
            sub=set_event.sub if set_event else None,
            is_core=irqn in CORE_IRQNS,
            loc=loc,
        )
    return interrupts
