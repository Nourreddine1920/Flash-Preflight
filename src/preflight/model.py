from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from preflight.findings import Diagnostic, Loc


class SourceKind(StrEnum):
    IOC = "ioc"
    CFILE = "c"
    OTHER = "other"  # produced by plugin parsers for non-STM32 config formats


@dataclass(frozen=True)
class McuInfo:
    raw_name: str | None = None
    cpn: str | None = None
    family: str | None = None
    core: str | None = None
    nvic_prio_bits: int | None = None
    hsi_hz: int | None = None
    usart_ip: str | None = None


@dataclass(frozen=True)
class PinAssignment:
    raw_name: str
    port: str
    number: int
    signal: str | None
    mode: str | None
    label: str | None
    alternate: str | None
    owner: str | None
    loc: Loc

    @property
    def canonical(self) -> str:
        return f"P{self.port}{self.number}"


@dataclass(frozen=True)
class PllConfig:
    source: str | None = None
    m: int | None = None
    n: int | None = None
    p: int | None = None
    q: int | None = None
    mul: int | None = None
    prediv: int | None = None


@dataclass(frozen=True)
class ClockTree:
    hse_hz: int | None = None
    hsi_hz: int | None = None
    lse_hz: int | None = None
    pll: PllConfig = field(default_factory=PllConfig)
    sysclk_source: str | None = None
    ahb_div: int | None = None
    apb1_div: int | None = None
    apb2_div: int | None = None
    sysclk_hz: int | None = None
    hclk_hz: int | None = None
    pclk1_hz: int | None = None
    pclk2_hz: int | None = None
    declared: dict[str, int] = field(default_factory=dict)
    locs: dict[str, Loc] = field(default_factory=dict)


@dataclass(frozen=True)
class Peripheral:
    name: str
    kind: str
    instance: int
    params: dict[str, str] = field(default_factory=dict)
    locs: dict[str, Loc] = field(default_factory=dict)


@dataclass(frozen=True)
class Interrupt:
    irqn: str
    enabled: bool
    preempt: int | None
    sub: int | None
    is_core: bool
    loc: Loc


@dataclass(frozen=True)
class HandleDecl:
    name: str
    kind: str
    loc: Loc


@dataclass(frozen=True)
class CFunction:
    name: str
    start_offset: int
    body_start: int
    body_end: int
    start_line: int


@dataclass(frozen=True)
class Event:
    kind: str  # "init" | "use" | "deinit" | "call"
    handle: str | None
    callee: str | None
    offset: int
    line: int
    fn_name: str
    brace_depth: int = 0


@dataclass(frozen=True)
class NvicEvent:
    irqn: str
    kind: str  # "set_priority" | "enable"
    preempt: int | None
    sub: int | None
    loc: Loc


@dataclass(frozen=True)
class CodeFacts:
    functions: dict[str, CFunction] = field(default_factory=dict)
    call_graph: dict[str, list[str]] = field(default_factory=dict)
    handles: dict[str, HandleDecl] = field(default_factory=dict)
    events: dict[str, list[Event]] = field(default_factory=dict)
    nvic_set: list[NvicEvent] = field(default_factory=list)
    nvic_enable: list[NvicEvent] = field(default_factory=list)
    priority_grouping: str | None = None
    entry_point: str | None = None


@dataclass(frozen=True)
class Config:
    source_path: str
    source_kind: SourceKind
    mcu: McuInfo = field(default_factory=McuInfo)
    pins: list[PinAssignment] = field(default_factory=list)
    clocks: ClockTree = field(default_factory=ClockTree)
    peripherals: dict[str, Peripheral] = field(default_factory=dict)
    interrupts: dict[str, Interrupt] = field(default_factory=dict)
    priority_group: str | None = None
    code: CodeFacts | None = None
    raw: object | None = None
    diagnostics: list[Diagnostic] = field(default_factory=list)
