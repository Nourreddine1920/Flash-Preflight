from preflight.parsers.properties import load


def test_basic_key_value():
    pf = load("File.Version=6\nMcu.Family=STM32F4\n")
    assert pf.get("File.Version") == "6"
    assert pf.get("Mcu.Family") == "STM32F4"


def test_comments_and_blank_lines_skipped():
    pf = load(
        "#MicroXplorer Configuration settings - do not modify\n"
        "\n"
        "!also a comment\n"
        "   \n"
        "Mcu.Family=STM32F4\n"
    )
    assert len(pf.entries) == 1
    assert pf.entries[0].key == "Mcu.Family"


def test_line_numbers_are_one_based():
    pf = load("A=1\nB=2\nC=3\n")
    assert [e.line for e in pf.entries] == [1, 2, 3]


def test_escaped_colon_in_value():
    pf = load(r"NVIC.USART2_IRQn=true\:5\:0\:false\:false\:true\:true\:true\:true")
    assert pf.get("NVIC.USART2_IRQn") == "true:5:0:false:false:true:true:true:true"


def test_line_continuation_odd_backslash():
    pf = load("USART2.IPParameters=VirtualMode,BaudRate,\\\n    WordLength,Parity\n")
    assert pf.get("USART2.IPParameters") == "VirtualMode,BaudRate,WordLength,Parity"


def test_continuation_leading_whitespace_stripped():
    pf = load("Key=abc\\\n      def\n")
    assert pf.get("Key") == "abcdef"


def test_even_trailing_backslashes_no_continuation():
    # \\\\ is an escaped backslash, not a continuation marker
    pf = load("Key=abc\\\\\nOther=1\n")
    assert pf.get("Key") == "abc\\"
    assert pf.get("Other") == "1"


def test_duplicate_keys_preserved_in_order():
    pf = load("PA2.Signal=USART2_TX\nPA2.Signal=S_TIM2_CH3\n")
    all_entries = pf.get_all("PA2.Signal")
    assert [e.value for e in all_entries] == ["USART2_TX", "S_TIM2_CH3"]
    assert [e.line for e in all_entries] == [1, 2]


def test_get_is_last_wins():
    pf = load("PA2.Signal=USART2_TX\nPA2.Signal=S_TIM2_CH3\n")
    assert pf.get("PA2.Signal") == "S_TIM2_CH3"


def test_duplicates_method():
    pf = load("A=1\nA=2\nB=1\n")
    dups = pf.duplicates()
    assert set(dups.keys()) == {"A"}
    assert len(dups["A"]) == 2


def test_unicode_escape():
    pf = load(r"Key=caf\u00e9")
    assert pf.get("Key") == "café"


def test_case_insensitive_lookup():
    pf = load("RCC.SYSCLKFreq_VALUE=168000000\n")
    assert pf.get_ci("RCC.SYSCLKFreq_Value") == "168000000"
    assert pf.get_ci("rcc.sysclkfreq_value") == "168000000"


def test_keys_with_prefix():
    pf = load("Mcu.Pin0=PA2\nMcu.Pin1=PA3\nMcu.PinsNb=2\n")
    prefixed = pf.keys_with_prefix("Mcu.Pin")
    assert {e.key for e in prefixed} == {"Mcu.Pin0", "Mcu.Pin1", "Mcu.PinsNb"}


def test_key_value_separator_variants():
    pf = load("A=1\nB:2\nC 3\nD = 4\n")
    assert pf.get("A") == "1"
    assert pf.get("B") == "2"
    assert pf.get("C") == "3"
    assert pf.get("D") == "4"


def test_crlf_line_endings():
    pf = load("A=1\r\nB=2\r\n")
    assert pf.get("A") == "1"
    assert pf.get("B") == "2"


def test_escaped_backslash_in_value():
    pf = load(r"Path=C:\\Users\\foo")
    assert pf.get("Path") == r"C:\Users\foo"
