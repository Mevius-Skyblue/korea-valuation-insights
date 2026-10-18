"""Reading YAML configs (P7-C4 fix C4-F3).

load(text) parses with PyYAML's C loader (libyaml) when it is installed, else with the pure-Python SafeLoader. Both are
"safe" loaders and give the same Python objects - checked on every config file of the repository (217 files, P7-C4) -
but the C one is about 9 times faster, and a confirmation reads about 17 config files.
"""

from __future__ import annotations

import yaml

_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def load(text):
    """Same as yaml.safe_load(text)."""
    return yaml.load(text, Loader=_LOADER)  # noqa: S506 - a safe loader (CSafeLoader / SafeLoader)
