"""Tests for module 5: workflow profiles (settings file)."""

import pytest

from manifest_doctor.config import ConfigError, resolve_settings


def write_config(tmp_path, text):
    path = tmp_path / "manifest-doctor.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_built_in_defaults_when_nothing_is_given():
    settings, sources = resolve_settings({}, config_path=None, profile=None)
    assert settings["algorithm"] == "md5"
    assert settings["prefix_mode"] == "suggest"
    assert settings["name_rules"] == "windows"
    assert settings["hash_extras"] is False
    assert settings["fail_on"] == "error"
    assert settings["severity"] == {}
    assert sources["algorithm"] == "default"


def test_profile_values_override_defaults(tmp_path):
    config = write_config(tmp_path, """
[profiles.cloud-delivery]
prefix_mode = "auto"
name_rules = "strict"
""")
    settings, sources = resolve_settings({}, config, "cloud-delivery")
    assert (settings["prefix_mode"], settings["name_rules"]) == ("auto", "strict")
    assert sources["prefix_mode"] == "profile cloud-delivery"


def test_command_line_overrides_the_profile(tmp_path):
    config = write_config(tmp_path, '[profiles.p]\nprefix_mode = "auto"\n')
    settings, sources = resolve_settings({"prefix_mode": "off"}, config, "p")
    assert settings["prefix_mode"] == "off"
    assert sources["prefix_mode"] == "command line"


def test_severity_overrides_are_read(tmp_path):
    config = write_config(tmp_path, '[profiles.tape-restore]\nseverity.EXTRA = "ERROR"\nfail_on = "warning"\n')
    settings, _ = resolve_settings({}, config, "tape-restore")
    assert settings["severity"] == {"EXTRA": "ERROR"}
    assert settings["fail_on"] == "warning"


@pytest.mark.parametrize("text, problem", [
    ('[profiles.p]\nprefix_mode = "sometimes"\n', "prefix_mode"),
    ('[profiles.p]\nalgorithm = "crc32"\n', "algorithm"),
    ('[profiles.p]\ncolour = "blue"\n', "colour"),
    ('[profiles.p]\nseverity.NOT_A_CODE = "ERROR"\n', "NOT_A_CODE"),
    ('[profiles.p]\nseverity.EXTRA = "PANIC"\n', "PANIC"),
    ('[profiles.p]\nhash_extras = "yes"\n', "hash_extras"),
    ('[profiles.p\n', "TOML"),
])
def test_mistakes_in_the_settings_file_stop_the_tool_with_a_clear_message(tmp_path, text, problem):
    config = write_config(tmp_path, text)
    with pytest.raises(ConfigError, match=problem):
        resolve_settings({}, config, "p")


def test_unknown_profile_name_is_an_error(tmp_path):
    config = write_config(tmp_path, '[profiles.p]\nprefix_mode = "auto"\n')
    with pytest.raises(ConfigError, match="no profile named 'q'"):
        resolve_settings({}, config, "q")


def test_profile_without_a_settings_file_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        resolve_settings({}, tmp_path / "missing.toml", "p")
