"""Offline test for the wallstreetcareers card parser (synthetic HTML)."""
from scrapers.wsc import _parse_cards, _age_days

HTML = """
<div class="row"><div>
  <a href="/jobs/111-quant-researcher">Quant Researcher</a>
  <a href="/companies/acme-1">Acme Capital</a>
  <a href="/jobs/full-time">Full-time</a>
  <a href="/jobs/in-new-york-new-york-united-states">New York, NY, US</a>
  <div class="job-posted-date">5h ago</div>
</div></div>
<div class="row"><div>
  <a href="/jobs/222-senior-trader">Senior Trader</a>
  <a href="/companies/beta-2">Beta</a>
  <div class="job-posted-date">2w ago</div>
</div></div>
"""


def test_parse():
    cards = _parse_cards(HTML)
    assert [c["title"] for c in cards] == ["Quant Researcher", "Senior Trader"]
    assert cards[0]["company"] == "Acme Capital" and cards[0]["location"].startswith("New York")
    assert cards[0]["age"] == 0 and cards[1]["age"] == 14


def test_age():
    assert _age_days("1d ago") == 1 and _age_days("3m ago") == 90 and _age_days("x") is None


if __name__ == "__main__":
    test_parse(); test_age(); print("ok")
