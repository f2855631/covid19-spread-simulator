"""模型核心的單元測試：用一個 3 節點的小世界，不需要任何資料檔。

執行：python -m pytest tests/ -q
"""
import copy
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "model"))
import seir  # noqa: E402


def make_world(days=90, travel=2000.0, R0=2.5):
    p = seir.load_params()
    p = copy.deepcopy(p)
    p["simulation"]["start"] = "2020-01-01"
    p["simulation"]["end"] = (pd.Timestamp("2020-01-01") + pd.Timedelta(days=days - 1)).date().isoformat()
    p["travel"]["passengers_per_route_per_day"] = 1.0   # 測試用：routes 直接當旅客數
    p["origin"].update({"node": "A", "seed_date": "2020-01-01", "seed_infected": 10, "travel_population": None})
    p["epidemiology"]["R0"] = R0
    p["lockdown"]["wuhan_date"] = "2099-01-01"
    p["reporting"]["testing_start"] = "2020-01-01"
    p["reporting"]["hubei_ramp_start"] = "2020-01-01"
    p["reporting"]["hubei_ramp_end"] = "2020-01-02"
    nodes = ["A", "B", "C"]
    N = np.array([1e6, 2e6, 5e5])
    tr = np.zeros((3, 3))
    tr[0, 1] = tr[1, 0] = travel          # A ↔ B 有航班
    tr[1, 2] = tr[2, 1] = travel / 2      # B ↔ C 有航班；A 與 C 之間沒有直飛
    dates = pd.date_range(p["simulation"]["start"], p["simulation"]["end"])
    zeros = np.zeros((len(dates), 3))
    inp = seir.Inputs(nodes, N, tr, dates, zeros.copy(), zeros.copy(), pd.Series([pd.NaT] * 3, index=nodes))
    return p, inp


def test_population_is_conserved_in_every_node():
    p, inp = make_world()
    r = seir.simulate(p, inp)
    total = r.S + r.E + r.I + r.R
    assert np.allclose(total, inp.N[None, :], rtol=1e-6)


def test_no_transmission_when_R0_is_zero():
    p, inp = make_world(R0=0.0)
    r = seir.simulate(p, inp)
    assert r.new_inf.sum() == pytest.approx(0.0, abs=1e-9)
    assert (r.arrival_day[1:] == -1).all()


def test_no_spread_without_travel():
    p, inp = make_world(travel=0.0)
    r = seir.simulate(p, inp)
    assert r.new_inf[:, 0].sum() > 100           # 起點本地有疫情
    assert r.imports.sum() == 0
    assert (r.arrival_day[1:] == -1).all()       # 其他節點不會被傳入


def test_spread_follows_the_network():
    p, inp = make_world()
    r = seir.simulate(p, inp)
    a, b, c = r.arrival_day
    assert 0 <= a < b < c                        # 必須先經過 B 才到得了 C
    assert r.source_share[0, 2] == 0             # A 不可能直接傳給 C
    assert r.source_share[:, 2].argmax() == 1


def test_lockdown_reduces_exports():
    p, inp = make_world()
    base = seir.simulate(p, inp)
    p2 = copy.deepcopy(p)
    p2["lockdown"]["wuhan_date"] = "2020-01-15"
    p2["lockdown"]["wuhan_travel_reduction"] = 0.95
    locked = seir.simulate(p2, inp)
    assert locked.imports[:, 1].sum() < 0.2 * base.imports[:, 1].sum()


def test_policy_slows_the_epidemic():
    p, inp = make_world()
    base = seir.simulate(p, inp)
    inp.stringency[:] = 80
    strict = seir.simulate(p, inp)
    assert strict.new_inf.sum() < base.new_inf.sum()


def test_reported_never_exceeds_infections():
    p, inp = make_world()
    r = seir.simulate(p, inp)
    infections = np.cumsum(r.new_inf + r.imports, axis=0)
    assert (r.reported_cum <= infections + 1e-9).all()


def test_no_case_is_reported_before_testing_exists():
    p, inp = make_world()
    p["reporting"]["testing_start"] = "2020-02-01"
    r = seir.simulate(p, inp)
    first_allowed = (pd.Timestamp("2020-02-01") - inp.dates[0]).days
    assert (r.reported_cum[:first_allowed] == 0).all()


def test_stochastic_runs_are_reproducible_with_a_seed():
    p, inp = make_world()
    r1 = seir.simulate(p, inp, stochastic=True, seed=42)
    r2 = seir.simulate(p, inp, stochastic=True, seed=42)
    assert np.array_equal(r1.imports, r2.imports)


def test_travel_parameters_take_effect_at_run_time():
    """校準會在模擬前改參數；航線旅客數必須在模擬時才換算，否則調了也沒用。"""
    p, inp = make_world()
    low = seir.simulate(p, inp)
    p2 = copy.deepcopy(p)
    p2["travel"]["passengers_per_route_per_day"] = 5.0
    high = seir.simulate(p2, inp)
    assert high.imports[:, 1].sum() > 2 * low.imports[:, 1].sum()
