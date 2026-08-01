"""Tests for the pure parsing logic behind /vaga (no Telegram mocking needed)."""
import pytest
from bot import parse_vaga_command


def test_url_only():
    url, desc = parse_vaga_command("https://www.linkedin.com/jobs/view/123")
    assert url == "https://www.linkedin.com/jobs/view/123"
    assert desc == ""


def test_url_with_pasted_description():
    body = "https://www.linkedin.com/jobs/view/123\nVaga de Java para o time backend.\nRequisitos: Java, SQL."
    url, desc = parse_vaga_command(body)
    assert url == "https://www.linkedin.com/jobs/view/123"
    assert desc == "Vaga de Java para o time backend.\nRequisitos: Java, SQL."


def test_invalid_url_returns_empty():
    url, desc = parse_vaga_command("nao é uma url")
    assert url == "" and desc == ""


def test_strips_surrounding_whitespace():
    url, desc = parse_vaga_command("  https://x.com/job  \n  texto aqui  ")
    assert url == "https://x.com/job"
    assert desc == "texto aqui"


from bot import _parse_gen_args


def test_parse_gen_args_id_only():
    assert _parse_gen_args("/cv a1b2c3d4") == ("a1b2c3d4", "auto")


def test_parse_gen_args_with_lang():
    assert _parse_gen_args("/cv a1b2c3d4 en") == ("a1b2c3d4", "en")
    assert _parse_gen_args("/cover deadbeef pt") == ("deadbeef", "pt")


def test_parse_gen_args_ignores_unknown_lang():
    # A third token that isn't pt/en shouldn't be treated as a language.
    assert _parse_gen_args("/cv a1b2c3d4 fr") == ("a1b2c3d4", "auto")


def test_parse_gen_args_empty():
    assert _parse_gen_args("/cv") == ("", "auto")
    assert _parse_gen_args("") == ("", "auto")


from bot import _parse_lang_arg


def test_parse_lang_arg_defaults_to_pt():
    assert _parse_lang_arg("/cvpadrao") == "pt"
    assert _parse_lang_arg("") == "pt"


def test_parse_lang_arg_accepts_en():
    assert _parse_lang_arg("/cvpadrao en") == "en"


def test_parse_lang_arg_ignores_unknown_lang():
    assert _parse_lang_arg("/cvpadrao fr") == "pt"


def test_parse_lang_arg_custom_default():
    assert _parse_lang_arg("/cvpadrao", default="en") == "en"
