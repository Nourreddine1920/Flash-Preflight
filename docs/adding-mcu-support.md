# Adding support for another MCU family

**Status:** the seams below exist and are tested. No second family ships yet.
Adding one should be a contained contribution: a parser, some fact tables,
and (optionally) a clock solver. The four rule *algorithms* do not change.

## What is generic and what is STM32-specific

| Piece | Generic? | Where |
|---|---|---|
| `Config` model (pins, clocks, peripherals, interrupts) | Generic | `model.py` |
| PF001 pin-conflict algorithm | Generic: works on `Config.pins` | `rules/pin_conflict.py` |
| PF004 priority checks | Mostly generic: uses `mcu.nvic_prio_bits` and ARM NVIC grouping (any Cortex-M) | `rules/nvic.py` |
| PF002 baud check | Rule is generic; the divisor math is per UART IP and the bus/clock tables are per family | `rules/clock_baud.py`, `clocks.py`, `knowledge/buses.py`, `knowledge/usart_ip.py` |
| PF003 init-before-use | Algorithm generic; the list of init/use function names is the STM32 HAL | `knowledge/hal_api.py` |
| `.ioc` / HAL `.c` parsing | STM32-specific | `parsers/ioc.py`, `parsers/cfile.py` |
| Family facts (core, HSI, USART IP, bus map) | Per family | `knowledge/` |

## The contribution path

1. **Write a parser plugin.** A class with `name`, `can_parse(path)` and
   `parse(path, mcu_override=None, hse_hz_override=None) -> Config`. Register it:

   ```toml
   [project.entry-points."preflight.parsers"]
   esp_sdkconfig = "preflight_esp32.parser:SdkconfigParser"
   ```

   Set `source_kind=SourceKind.OTHER`. Fill in only what you can determine;
   leave the rest empty/`None` and the rules skip themselves with a reason
   instead of guessing. Plugin parsers are consulted only for file types the
   built-ins don't claim (not `.ioc`, `.c`, `.h`).
2. **Add family facts** if you want PF002/PF004 to apply: rows in the
   `knowledge/` tables (`CORE_BY_FAMILY`, bus map, ...). They are plain dicts.
3. **Register a clock solver** if the clock tree is derivable:
   `clocks.register_clock_solver("<family>", fn)`. Otherwise PF002 falls back to
   frequencies your parser records in `ClockTree.declared`.
4. **Need a genuinely new check?** Write a rule plugin
   (`preflight.rules` entry point, see CONTRIBUTING.md). Don't edit the core rules.
5. **Fixtures + tests:** a `clean` and `broken_<mechanism>` fixture per check.

## Known limits of the seams

- Rules that special-case `SourceKind.IOC` / `SourceKind.CFILE` (PF001's stale-pin
  check, PF003) won't fire for `OTHER`; they report `SKIPPED` where they can't run.
- Family tables are module-level dicts. An out-of-tree plugin can add rows when
  its entry point loads, but there is no formal registration API for them yet.

## Suggested first external target: ESP32 via ESP-IDF `sdkconfig`

- The file is flat `CONFIG_X=value`, close to `.ioc`; the existing key/value
  reader in `parsers/properties.py` is a starting point.
- ESP32 has real, well-known pin bug classes that a family table can express:
  strapping pins, pins wired to flash, and input-only pins configured as outputs.
- Large user base, so contributions and real-world findings are likely.

Caveat: many ESP32 pins are assigned in C code (or `menuconfig` options), not one
central file, so early coverage will be narrower than for CubeMX. nRF/Zephyr
devicetree is richer but needs a devicetree parser, a bigger first step.
