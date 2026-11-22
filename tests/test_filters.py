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


def test_weak_signals_dont_admit_noise():
    for t in ["Associate Tax Derivatives Accountant", "Junior Audit Associate - Derivatives Valuation",
              "Entry Level Claims Modeling Analyst", "Associate, Employee Benefits Modeling",
              "Marketing Mix Modeling Analyst", "Clinical Pharmacology Modeling Associate",
              "Insurance Catastrophe Modeler - Associate", "Retail Systematic Merchandising Associate",
              "Systematic Review Analyst, Clinical", "3D Modeler Entry Level", "Hydrologic Modeler I",
              "Supply Chain Modeling Analyst", "Energy Trading Analyst", "Sales Trading Analyst",
              "Jr. Modeling & Simulation Engineer", "Power Market Analyst, Market Modeling & Strategy",
              "Research Scientist - World Modeling", "Portfolio Trading Analyst - Wealth Management"]:
        assert not filters.is_early_career(_row(t)), t


def test_weak_signals_admit_real_roles():
    for t in ["Associate, Model Development", "Associate, Initial Margining Modeling",
              "Residential Mortgage Modeler", "USD Rates Trading Analyst",
              "Systematic Derivatives - Associate", "Credit Risk Modeler"]:
        assert filters.is_early_career(_row(t)), t


def test_nov2026_vocab_additions():
    for t in ["Liquidity Metrics Strats, Associate", "Stress Testing - Wholesale Credit Risk - Associate"]:
        assert filters.is_early_career(_row(t)), t
    for t in ["Quantitative Researcher - Experienced Hire", "Risk Modeler III, Model Risk",
              "Quantitative Trading & Research - 2027 ReEntry", "Quant Developer Stage"]:
        assert not filters.is_early_career(_row(t)), t


def test_location_format_variants_collapse():
    df = pd.DataFrame([
        _row("Quantitative Researcher", "Acme", "New York, NY"),
        _row("Quantitative Researcher", "Acme", "New York, NY, USA"),
        _row("Quantitative Researcher", "Acme", "New York, New York, United States"),
    ])
    assert len(filters.apply_filters(df)) == 1


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


def test_summer_in_title_is_excluded_but_not_in_jd_or_company():
    for t in ["Summer 2027 Quantitative Researcher", "Quantitative Trading Summer Program",
              "Summer Quant Trader", "Quant Strategist - Summer Analyst"]:
        assert not filters.is_early_career(_row(t, desc="new grad")), t
    # "Summer" only in the JD or company name must not exclude a genuine role
    assert filters.is_early_career(_row("Junior Quantitative Analyst",
                                        company="Summer Street Capital",
                                        desc="Not a summer role; full-time start 2027"))


def test_wells_fargo_blocked_by_company():
    for c in ["Wells Fargo", "Wells Fargo & Company", "WELLS FARGO Securities"]:
        assert not filters.is_early_career(_row("Quantitative Analyst - Entry Level", company=c)), c
    assert filters.is_early_career(_row("Quantitative Analyst - Entry Level", company="Wellington Management"))


def test_aqr_alias_dedups_brand_and_legal_name():
    a = filters.make_dedup_key("Quantitative Researcher", "AQR Capital", "Greenwich, CT")
    b = filters.make_dedup_key("Quantitative Researcher", "AQR Capital Management, LLC", "Greenwich, CT")
    assert a == b
