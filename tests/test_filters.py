"""Offline tests for the Nov 2026 filter changes (no network / API keys)."""
import pandas as pd
import filters


def _row(title, company="Acme", location="New York, NY", desc=""):
    return pd.Series({"title": title, "company": company, "location": location, "description": desc})


def test_title_gate_widened():
    for t in ["Systematic Derivatives - Associate", "Junior Trading Analyst",
              "Systematic Credit Strategies Research - Associate",
              "Credit Risk Modeler", "Quantitative Model Validation Analyst"]:
        assert filters.is_early_career(_row(t)), t


def test_still_rejects_senior_intern_and_noise():
    for t in ["Senior Quantitative Developer", "Quantitative Research Intern",
              "Audit Associate (January 2027)", "Director, Quantitative Research"]:
        assert not filters.is_early_career(_row(t)), t


def test_quant_titles_never_denied_by_noise_list():
    assert filters.noise_hit("Quant Analyst - Insurance Capital Solutions") == ""
    assert filters.noise_hit("Tax Associate, State and Local Tax") == "Tax"


def test_cities_stay_distinct_in_run():
    df = pd.DataFrame([
        _row("Quantitative Model Validation Analyst", "U.S. Bank", "Minneapolis, MN"),
        _row("Quantitative Model Validation Analyst", "U.S. Bank", "Charlotte, NC"),
        _row("Quantitative Model Validation Analyst", "U.S. Bank", "Charlotte, NC"),  # true dup
    ])
    out = filters.apply_filters(df)
    assert len(out) == 2, len(out)


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
    print("ok")
