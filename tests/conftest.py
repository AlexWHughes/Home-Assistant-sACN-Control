"""Load HA-free integration modules as package `sacn_control` without importing Home Assistant."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

PACKAGE = "sacn_control"
PACKAGE_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "sacn_control"
HA_FREE_MODULES = ("const", "dmx", "pixels", "models", "universe")


def _ensure_package() -> None:
    if PACKAGE in sys.modules and all(
        f"{PACKAGE}.{name}" in sys.modules for name in HA_FREE_MODULES
    ):
        return
    package = ModuleType(PACKAGE)
    package.__path__ = [str(PACKAGE_DIR)]
    package.__package__ = PACKAGE
    sys.modules[PACKAGE] = package
    for name in HA_FREE_MODULES:
        spec = importlib.util.spec_from_file_location(
            f"{PACKAGE}.{name}",
            PACKAGE_DIR / f"{name}.py",
            submodule_search_locations=[str(PACKAGE_DIR)],
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load {name}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"{PACKAGE}.{name}"] = module
        spec.loader.exec_module(module)
        setattr(package, name, module)


_ensure_package()
