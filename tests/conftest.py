"""Load the Home Assistant-independent modules without importing Home Assistant.

custom_components/gouly/__init__.py imports homeassistant, so the pure modules are
loaded under a stand-in package name instead.
"""

import importlib.util
import sys
import types
from pathlib import Path

COMPONENT_DIR = Path(__file__).resolve().parent.parent / "custom_components" / "gouly"
PACKAGE = "gouly_core"


def _load_pure_modules() -> None:
    if PACKAGE in sys.modules:
        return
    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(COMPONENT_DIR)]
    sys.modules[PACKAGE] = package
    for name in ("protocol", "discovery", "connection"):
        spec = importlib.util.spec_from_file_location(f"{PACKAGE}.{name}", COMPONENT_DIR / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        setattr(package, name, module)


_load_pure_modules()
