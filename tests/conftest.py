"""Load `registry_migration` without a Home Assistant installation.

The module imports `DOMAIN` from `.constants` and, inside the one HA-facing
function, `homeassistant.helpers`. Only the pure planning half is under test
here, so a synthetic package with the real `constants` attached is enough —
the HA imports are function-local and never execute.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "nuki_ng"

_pkg = types.ModuleType("nuki_ng_under_test")
_pkg.__path__ = [str(COMPONENT)]
sys.modules["nuki_ng_under_test"] = _pkg


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"nuki_ng_under_test.{name}", COMPONENT / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    setattr(_pkg, name, module)
    return module


constants = _load("constants")
migration = _load("registry_migration")
