"""Module 5: settings. Built-in defaults, then a workflow profile, then the command line.

Each later layer overrides the earlier one, and the report records where every
value came from, so a result can always be traced back to its settings.
"""

import tomllib
from pathlib import Path

from .checks import NAME_RULES
from .findings import DEFAULT_SEVERITY, ERROR, INFO, WARNING
from .manifest import HASH_LENGTH

DEFAULTS = {
    "algorithm": "md5",
    "prefix_mode": "suggest",
    "name_rules": "windows",
    "hash_extras": False,
    "fail_on": "error",
    "severity": {},
}

ALLOWED = {
    "algorithm": set(HASH_LENGTH),
    "prefix_mode": {"suggest", "auto", "off"},
    "name_rules": set(NAME_RULES),
    "fail_on": {"error", "warning"},
}


class ConfigError(Exception):
    """The settings can't be used. The tool stops (exit code 2) rather than guess."""


def resolve_settings(cli_values, config_path, profile):
    settings = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULTS.items()}
    sources = {k: "default" for k in DEFAULTS}

    if profile is not None:
        for key, value in _load_profile(Path(config_path), profile).items():
            settings[key] = value
            sources[key] = f"profile {profile}"

    for key, value in cli_values.items():
        settings[key] = value
        sources[key] = "command line"
    return settings, sources


def _load_profile(path, name):
    if not path.exists():
        raise ConfigError(f"settings file {path} not found (needed for --profile {name})")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"settings file {path} is not valid TOML: {error}") from error
    profiles = data.get("profiles", {})
    if name not in profiles:
        raise ConfigError(f"settings file {path} has no profile named {name!r}")
    profile = profiles[name]
    _validate(profile, name)
    return profile


def _validate(profile, name):
    for key, value in profile.items():
        where = f"profile {name!r}, setting {key!r}"
        if key not in DEFAULTS:
            raise ConfigError(f"{where}: unknown setting {key!r}")
        if key in ALLOWED and value not in ALLOWED[key]:
            raise ConfigError(f"{where}: {value!r} is not one of {sorted(ALLOWED[key])}")
        if key == "hash_extras" and not isinstance(value, bool):
            raise ConfigError(f"{where}: hash_extras must be true or false")
        if key == "severity":
            for code, level in value.items():
                if code not in DEFAULT_SEVERITY:
                    raise ConfigError(f"{where}: unknown finding code {code!r}")
                if level not in (ERROR, WARNING, INFO):
                    raise ConfigError(f"{where}: {level!r} must be ERROR, WARNING or INFO")
