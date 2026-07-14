"""DST correctness for the scheduler's local-time computation.

The scheduler previously used a hardcoded timedelta(hours=-7) (PDT), which drifts
an hour during Pacific Standard Time. This verifies the zoneinfo-based _to_local()
resolves 6:00 AM PT correctly in both PDT (summer) and PST (winter).

Run: ./venv/bin/python tests/test_scheduler_dst.py
"""
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from web import _to_local  # noqa: E402

TZ = "America/Los_Angeles"


def test_pdt_summer():
    # July → PDT (UTC-7). 13:00 UTC == 06:00 local (the daily brief hour).
    local = _to_local(datetime(2026, 7, 1, 13, 0, tzinfo=timezone.utc), TZ)
    assert local.hour == 6, local


def test_pst_winter():
    # January → PST (UTC-8). 14:00 UTC == 06:00 local. The OLD -7 offset gave 07:00 (wrong).
    local = _to_local(datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc), TZ)
    assert local.hour == 6, local


def test_date_boundary():
    # 2026-07-02 06:00 UTC is still 2026-07-01 23:00 PDT (prior local day) — proves
    # today/current_hour derive from local wall-clock, not UTC.
    local = _to_local(datetime(2026, 7, 2, 6, 0, tzinfo=timezone.utc), TZ)
    assert local.date().isoformat() == "2026-07-01", local
    assert local.hour == 23, local


if __name__ == "__main__":
    test_pdt_summer()
    test_pst_winter()
    test_date_boundary()
    old_winter = (datetime(2026, 1, 1, 14, 0) + timedelta(hours=-7)).hour
    new_winter = _to_local(datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc), TZ).hour
    print(f"winter 14:00 UTC → OLD fixed -7 offset = {old_winter}:00 (WRONG), "
          f"NEW zoneinfo = {new_winter}:00 (correct 6:00)")
    print("All DST assertions passed.")
