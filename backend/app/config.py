"""
Verdant config — loads environment variables and all registry YAMLs.
All tunable constants live in YAML, never hardcoded here.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).parent.parent  # backend/
REGISTRY_DIR = Path(__file__).parent / "registry"
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

load_dotenv(ROOT.parent / ".env")  # verdant/.env

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------


def _bool(key: str, default: bool = False) -> bool:
    return os.getenv(key, "1" if default else "0").strip() == "1"


def _int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


MOCK_LLM: bool = _bool("MOCK_LLM", default=False)
USE_SYNTHETIC_CARBON: bool = _bool("USE_SYNTHETIC_CARBON", default=False)
SEED: int = _int("SEED", 42)

GEMINI_API_KEY: str | None = os.getenv("GEMINI_API_KEY")
ELECTRICITYMAPS_TOKEN: str | None = os.getenv("ELECTRICITYMAPS_TOKEN")
OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")

DB_PATH: Path = DATA_DIR / "verdant.db"
CARBON_SNAPSHOT_PATH: Path = DATA_DIR / "carbon_snapshot.json"

# ---------------------------------------------------------------------------
# Registry loaders
# ---------------------------------------------------------------------------


def _load_yaml(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=1)
def get_models_registry() -> dict[str, Any]:
    base = _load_yaml(REGISTRY_DIR / "models.yaml")
    # Merge calibrated overrides if they exist
    calibrated_path = REGISTRY_DIR / "calibrated.yaml"
    if calibrated_path.exists():
        overrides = _load_yaml(calibrated_path)
        for model in base.get("models", []):
            if model["id"] in overrides:
                model.update(overrides[model["id"]])
    return base


@lru_cache(maxsize=1)
def get_sites_registry() -> dict[str, Any]:
    return _load_yaml(REGISTRY_DIR / "sites.yaml")


@lru_cache(maxsize=1)
def get_step_types_registry() -> dict[str, Any]:
    return _load_yaml(REGISTRY_DIR / "step_types.yaml")


@lru_cache(maxsize=1)
def get_equivalents_registry() -> dict[str, Any]:
    return _load_yaml(REGISTRY_DIR / "equivalents.yaml")


@lru_cache(maxsize=1)
def get_presets_registry() -> dict[str, Any]:
    return _load_yaml(REGISTRY_DIR / "presets.yaml")


# ---------------------------------------------------------------------------
# Convenience accessors
# ---------------------------------------------------------------------------


def get_model_by_id(model_id: str) -> dict[str, Any] | None:
    """Look up a model config by its alias (e.g. 'small', 'medium', 'large')."""
    reg = get_models_registry()
    for m in reg.get("models", []):
        if m["id"] == model_id:
            return m
    return None


def get_site_by_id(site_id: str) -> dict[str, Any] | None:
    reg = get_sites_registry()
    for s in reg.get("sites", []):
        if s["id"] == site_id:
            return s
    return None


def get_weights_for_preset(preset_name: str) -> dict[str, float] | None:
    presets = get_presets_registry()
    return presets.get("presets", {}).get(preset_name)


# ---------------------------------------------------------------------------
# Startup model validation
# ---------------------------------------------------------------------------


def validate_model_ids() -> tuple[list[str], list[str]]:
    """
    Attempt to list available Gemini models and warn if configured api_ids
    are missing. Returns (ok_list, missing_list).
    This is a best-effort check — if the API is unreachable, return empty missing.
    """
    reg = get_models_registry()
    configured: list[str] = [
        m.get("api_id", "")
        for m in reg.get("models", [])
        if m.get("provider") == "gemini" and m.get("api_id")
    ]

    if MOCK_LLM:
        # In mock mode all models are "available"
        return configured, []

    if not GEMINI_API_KEY:
        return [], configured  # can't check without a key

    try:
        from google import genai  # type: ignore

        client = genai.Client(api_key=GEMINI_API_KEY)
        # API returns "models/gemini-2.5-flash" — strip prefix for comparison
        available_ids = {
            m.name.removeprefix("models/") for m in client.models.list()  # type: ignore
        }
        ok = [c for c in configured if c in available_ids]
        missing = [c for c in configured if c not in available_ids]
        return ok, missing
    except Exception:
        return [], []  # network/import error — skip silently at startup

