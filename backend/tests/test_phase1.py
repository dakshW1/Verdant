"""
Phase 1 tests — carbon synthetic provider and models registry.
Run with: pytest backend/tests/test_phase1.py -v
"""
from __future__ import annotations

import time

import pytest

from app.carbon.synthetic import SyntheticCarbonProvider, synthetic_ci_mean, synthetic_ci_sigma
from app.config import get_models_registry, get_sites_registry, get_step_types_registry


# ─── Synthetic CI model ───────────────────────────────────────────────────────

class TestSyntheticCIMean:
    def test_fi_at_noon_lower_than_midnight(self):
        """Finland: wind at night, so CI higher midday vs midnight... actually CI has wind_night_dip."""
        # FI has wind_night_dip=0.30, so CI is LOWER at night
        t_noon = 12 * 3600 - 2 * 3600  # 12:00 UTC = 14:00 FI (utc+2)
        t_midnight = 0  # 00:00 UTC = 02:00 FI
        ci_noon = synthetic_ci_mean("FI", float(t_noon))
        ci_midnight = synthetic_ci_mean("FI", float(t_midnight))
        # At midnight FI: wind_night_dip applied → CI should be lower
        assert ci_midnight < ci_noon

    def test_in_so_solar_peak_lower(self):
        """IN-SO: high solar_dip, so CI should be lower at solar peak (~noon local)."""
        utc_offset = 5.5 * 3600
        t_noon_local = 12 * 3600 - utc_offset  # UTC time when local is noon
        t_night_local = 22 * 3600 - utc_offset
        ci_noon = synthetic_ci_mean("IN-SO", float(t_noon_local))
        ci_night = synthetic_ci_mean("IN-SO", float(t_night_local))
        assert ci_noon < ci_night

    def test_unknown_zone_returns_midrange(self):
        ci = synthetic_ci_mean("UNKNOWN", 0.0)
        assert ci == 400.0

    def test_clipped_to_minimum(self):
        """CI should never fall below 20 gCO2e/kWh."""
        for zone in ["FI", "IN-SO", "IN-WE", "SG", "IN-NO"]:
            ci = synthetic_ci_mean(zone, 0.0)
            assert ci >= 20.0, f"Zone {zone} CI below minimum: {ci}"


class TestSyntheticCISigma:
    def test_sigma_grows_with_horizon(self):
        s0 = synthetic_ci_sigma("FI", 0)
        s6 = synthetic_ci_sigma("FI", 6)
        s24 = synthetic_ci_sigma("FI", 24)
        assert s0 < s6 < s24

    def test_unknown_zone_sigma(self):
        s = synthetic_ci_sigma("UNKNOWN", 10.0)
        assert s == 30.0


class TestSyntheticCarbonProvider:
    @pytest.mark.asyncio
    async def test_forecast_returns_correct_structure(self):
        provider = SyntheticCarbonProvider()
        start_ts = int(time.time())
        fc = await provider.forecast("FI", start_ts, 3600, 1800)
        assert fc.zone == "FI"
        assert fc.window_s == 1800
        assert len(fc.mean) == 2
        assert len(fc.sigma) == 2
        assert fc.source == "synthetic"

    @pytest.mark.asyncio
    async def test_forecast_all_values_positive(self):
        provider = SyntheticCarbonProvider()
        start_ts = int(time.time())
        for zone in ["FI", "IN-SO", "SG"]:
            fc = await provider.forecast(zone, start_ts, 7200, 1800)
            assert all(v > 0 for v in fc.mean), f"Non-positive mean for {zone}"
            assert all(v > 0 for v in fc.sigma), f"Non-positive sigma for {zone}"

    @pytest.mark.asyncio
    async def test_forecast_deterministic_with_same_start(self):
        provider = SyntheticCarbonProvider()
        start_ts = 1_700_000_000  # fixed timestamp
        fc1 = await provider.forecast("FI", start_ts, 3600, 1800)
        fc2 = await provider.forecast("FI", start_ts, 3600, 1800)
        assert fc1.mean == fc2.mean


# ─── Models registry ─────────────────────────────────────────────────────────

class TestModelsRegistry:
    def test_has_three_tiers(self):
        reg = get_models_registry()
        tiers = {m["tier"] for m in reg.get("models", [])}
        assert "S" in tiers
        assert "M" in tiers
        assert "L" in tiers

    def test_all_gemini_models_have_api_id(self):
        reg = get_models_registry()
        for m in reg.get("models", []):
            if m.get("provider") == "gemini":
                assert "api_id" in m, f"Model {m['id']} missing api_id"

    def test_ollama_model_has_device_power(self):
        reg = get_models_registry()
        ollama = [m for m in reg.get("models", []) if m.get("provider") == "ollama"]
        assert len(ollama) >= 1
        for m in ollama:
            assert "device_power_w" in m, f"Ollama model {m['id']} missing device_power_w"

    def test_pricing_fields_present(self):
        reg = get_models_registry()
        for m in reg.get("models", []):
            if m.get("provider") == "gemini":
                assert "price_in_per_mtok_usd" in m
                assert "price_out_per_mtok_usd" in m


class TestStepTypesRegistry:
    def test_all_step_types_have_quality_priors(self):
        reg = get_step_types_registry()
        required_types = {"planning", "extraction", "summarization", "reasoning",
                          "verification", "formatting", "code"}
        present = set(reg.get("step_types", {}).keys())
        assert required_types == present

    def test_quality_priors_in_range(self):
        reg = get_step_types_registry()
        for name, st in reg.get("step_types", {}).items():
            for tier, q in st.get("q", {}).items():
                assert 0.0 <= q <= 1.0, f"Quality {q} out of range for {name}/{tier}"

    def test_p_accept_s_in_range(self):
        reg = get_step_types_registry()
        for name, st in reg.get("step_types", {}).items():
            p = st.get("p_accept_S", 0.65)
            assert 0.0 <= p <= 1.0


class TestSitesRegistry:
    def test_sites_have_zone_and_pue(self):
        reg = get_sites_registry()
        for s in reg.get("sites", []):
            assert "zone" in s, f"Site {s['id']} missing zone"
            assert "pue" in s, f"Site {s['id']} missing pue"

    def test_synthetic_ci_params_present(self):
        reg = get_sites_registry()
        synth = reg.get("synthetic_ci", {})
        assert len(synth) >= 3, "synthetic_ci should have entries for multiple zones"
        for zone, params in synth.items():
            assert "base" in params, f"Zone {zone} missing 'base' in synthetic_ci"
