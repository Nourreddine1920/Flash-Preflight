from pathlib import Path

from preflight.parsers.clex import split_functions, strip_and_index

FIXTURES = Path(__file__).parent / "fixtures"


def test_stripped_source_same_length_as_original():
    src = 'int main(void) { /* comment */ printf("hi\\n"); }\n'
    result = strip_and_index(src)
    assert len(result.stripped) == len(result.original)


def test_block_comment_is_blanked():
    src = "int x; /* a comment with { braces } inside */ int y;\n"
    result = strip_and_index(src)
    assert "{" not in result.stripped
    assert "comment" not in result.stripped
    assert "int x" in result.stripped
    assert "int y" in result.stripped


def test_line_comment_is_blanked():
    src = "int x; // HAL_UART_Transmit(&h, 0, 0, 0);\nint y;\n"
    result = strip_and_index(src)
    assert "HAL_UART_Transmit" not in result.stripped
    assert "int y" in result.stripped


def test_string_literal_is_blanked():
    src = 'char *s = "HAL_UART_Transmit(&h, 0, 0, 0)";\n'
    result = strip_and_index(src)
    assert "HAL_UART_Transmit" not in result.stripped


def test_string_containing_comment_markers_not_treated_as_comment():
    src = 'char *s = "/* not a comment */ still string";\nint y;\n'
    result = strip_and_index(src)
    # Everything inside the string, including /* */ markers, is blanked
    assert "not a comment" not in result.stripped
    assert "int y" in result.stripped


def test_comment_containing_quote_not_treated_as_string():
    src = '/* a "quote" inside a comment */\nint y = 1;\n'
    result = strip_and_index(src)
    assert "quote" not in result.stripped
    assert "int y = 1" in result.stripped


def test_char_literal_blanked():
    src = "char c = '\"'; int y;\n"
    result = strip_and_index(src)
    assert "int y" in result.stripped


def test_line_numbers_preserved_after_stripping():
    src = "line1;\n/* comment\nspanning\nlines */\nline5;\n"
    result = strip_and_index(src)
    idx = result.stripped.index("line5")
    assert result.line_for_offset(idx) == 5


def test_if_0_block_is_blanked():
    src = (
        "int main(void) {\n"
        "  HAL_UART_Init(&huart2);\n"
        "#if 0\n"
        "  HAL_UART_Init(&huart2);\n"
        "#endif\n"
        "}\n"
    )
    result = strip_and_index(src)
    assert result.stripped.count("HAL_UART_Init") == 1


def test_ifdef_block_is_not_blanked():
    src = (
        "int main(void) {\n"
        "#ifdef USE_FEATURE\n"
        "  HAL_UART_Init(&huart2);\n"
        "#endif\n"
        "}\n"
    )
    result = strip_and_index(src)
    assert "HAL_UART_Init" in result.stripped
    assert result.conditionals_not_evaluated == 1


def test_if_0_else_keeps_else_branch():
    src = (
        "int main(void) {\n"
        "#if 0\n"
        "  HAL_SPI_Init(&hspi1);\n"
        "#else\n"
        "  HAL_UART_Init(&huart2);\n"
        "#endif\n"
        "}\n"
    )
    result = strip_and_index(src)
    assert "HAL_SPI_Init" not in result.stripped
    assert "HAL_UART_Init" in result.stripped


def test_lexer_traps_fixture_produces_no_visible_hal_calls_outside_main_use():
    src = (FIXTURES / "pf003_lexer_traps.c").read_text()
    result = strip_and_index(src)
    # The only real, non-string, non-comment token stream should contain no
    # HAL_SPI_Transmit or HAL_UART_Transmit call at all -- every occurrence in
    # this fixture is inside a comment or a string literal.
    assert "HAL_SPI_Transmit" not in result.stripped
    assert "HAL_UART_Transmit" not in result.stripped


def test_split_functions_finds_main():
    src = "#include <x.h>\nint main(void) {\n  return 0;\n}\n"
    result = strip_and_index(src)
    functions = split_functions(result)
    names = {f.name for f in functions}
    assert "main" in names


def test_split_functions_brace_matching_with_nested_braces():
    src = (
        "static void MX_GPIO_Init(void) {\n"
        "  if (1) {\n"
        "    int x = 1;\n"
        "  }\n"
        "  for (int i = 0; i < 3; i++) { x++; }\n"
        "}\n"
        "int main(void) {\n"
        "  return 0;\n"
        "}\n"
    )
    result = strip_and_index(src)
    functions = {f.name: f for f in split_functions(result)}
    assert set(functions) == {"MX_GPIO_Init", "main"}
    gpio_body = result.stripped[functions["MX_GPIO_Init"].body_start : functions["MX_GPIO_Init"].body_end]
    assert "x++" in gpio_body
    main_body = result.stripped[functions["main"].body_start : functions["main"].body_end]
    assert "return 0" in main_body


def test_split_functions_ignores_declarations():
    src = "void MX_USART2_UART_Init(void);\nvoid MX_USART2_UART_Init(void) {\n  huart2.Instance = USART2;\n}\n"
    result = strip_and_index(src)
    functions = split_functions(result)
    assert len(functions) == 1
    assert functions[0].name == "MX_USART2_UART_Init"


def test_function_qualifiers_and_pointer_return_handled():
    src = "static __weak HAL_StatusTypeDef *MX_Foo_Init(void) {\n  return 0;\n}\n"
    result = strip_and_index(src)
    functions = split_functions(result)
    assert len(functions) == 1
    assert functions[0].name == "MX_Foo_Init"


def test_backslash_newline_splice_in_line_comment():
    src = "int x; // this comment continues \\\nonto the next line HAL_UART_Init(&h);\nint y;\n"
    result = strip_and_index(src)
    assert "HAL_UART_Init" not in result.stripped
    assert "int y" in result.stripped
