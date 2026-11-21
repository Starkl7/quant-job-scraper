"""Offline tests for runlog.py health flags (no network / API keys needed)."""
import json
import os
import tempfile


def test_flags_and_write():
    with tempfile.TemporaryDirectory() as d:
        os.environ["RUN_LOG_DIR"] = d
        import importlib, runlog
        importlib.reload(runlog)

        r = runlog.RunLog("unit")
        for i in range(8):
            r.query("q", f"city{i}", 50, "ok")
        assert r.flags() == []                      # 0% failed → healthy

        r.query("q", "NYC", 10, "partial_errors", attempts=2, errors=3)
        r.query("q", "SF", 0, "timeout")
        r.query("q", "BOS", 0, "zero")
        assert any("queries failed" in f for f in r.flags())   # 3/11 > 20%

        r.source("Citi", "workday", 0)
        r.source("Jane Street", "greenhouse", 40)
        assert any("Citi" in f for f in r.flags())

        r.write()
        line = open(os.path.join(d, runlog.LOG_FILE)).read().strip()
        rec = json.loads(line)
        assert rec["pipeline"] == "unit"
        assert rec["scrape"]["queries_failed"] == 3
        assert rec["ats_sources"]["zero_listing"] == ["Citi"]


if __name__ == "__main__":
    test_flags_and_write()
    print("ok")
