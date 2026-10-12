"""網頁版模型（app/sim_core.js）與 Python 版（model/seir.py）結果必須一致。

需要 Node.js；沒有安裝時自動略過。先執行 python app/build_web_data.py 產生 app/web_data.json。
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "model"))
import seir  # noqa: E402

NODE = shutil.which("node")
DATA = ROOT / "app" / "web_data.json"


@pytest.mark.skipif(NODE is None, reason="沒有安裝 Node.js")
@pytest.mark.skipif(not DATA.exists(), reason="先執行 python app/build_web_data.py")
def test_js_model_matches_python():
    out = subprocess.run([NODE, str(ROOT / "app" / "parity_check.js"), str(DATA)],
                         capture_output=True, text=True, check=True)
    js = json.loads(out.stdout)
    p = seir.load_params()
    r = seir.simulate(p, seir.load_inputs(p), flow_min=None)
    assert np.array_equal(js["detect"], r.detect_day)
    assert np.array_equal(js["arrival"], r.arrival_day)
    np.testing.assert_allclose(js["reportedLast"], r.reported_cum[-1], rtol=1e-9, atol=1e-6)
    np.testing.assert_allclose(js["totalInf"], r.new_inf.sum(axis=0), rtol=1e-9, atol=1e-6)
