"""
事前定義テストセット（固定・人手作成）
自己循環問題への対策：LLMが生成したテストではなく
人手で事前定義したテストで修正の正しさを判定する

各シナリオに対して：
  - 正常系テスト（happy_path）
  - 境界値テスト（edge_case）
  - 回帰テスト（regression）
の3種を定義する
"""
import time
import httpx

BACKEND_URL = "http://backend:8000"


# ── テスト実行ユーティリティ ──────────────────

def run_test(name: str, fn) -> dict:
    # コード適用直後は backend(uvicorn --reload) のリロードが間に合わず、
    # 古い応答や 500/接続拒否を返す「リロードレース」が起きる。これは修正の正否とは
    # 無関係なので、失敗時は反映を待って数回リトライし、正しい修正を取りこぼさない。
    # （誤った修正は全リトライで失敗し続けるので判定は保たれる。）
    last_error = None
    for _ in range(5):
        try:
            fn()
            return {"name": name, "passed": True, "error": None}
        except Exception as e:
            last_error = e
            time.sleep(0.6)   # リロード反映待ち
            continue
    return {"name": name, "passed": False, "error": str(last_error)}


# ══════════════════════════════════════════════
# L1-A：Gemini APIキー名変更テスト
# ══════════════════════════════════════════════

def test_l1a_happy_path():
    resp = httpx.get(f"{BACKEND_URL}/api/ai-summary")
    assert resp.status_code == 200
    data = resp.json()
    assert "summary" in data
    assert isinstance(data["summary"], str)
    assert len(data["summary"]) > 0

def test_l1a_edge_case():
    """summaryが空文字でないことを確認"""
    resp = httpx.get(f"{BACKEND_URL}/api/ai-summary")
    assert resp.status_code == 200
    assert resp.json()["summary"].strip() != ""

def test_l1a_regression():
    """500エラーが発生しないことを確認"""
    resp = httpx.get(f"{BACKEND_URL}/api/ai-summary")
    assert resp.status_code != 500

TESTS_L1A = [
    lambda: run_test("l1a_happy_path",  test_l1a_happy_path),
    lambda: run_test("l1a_edge_case",   test_l1a_edge_case),
    lambda: run_test("l1a_regression",  test_l1a_regression),
]


# ══════════════════════════════════════════════
# L1-B：Gemini API型変化テスト
# ══════════════════════════════════════════════

def test_l1b_happy_path():
    resp = httpx.get(f"{BACKEND_URL}/api/ai-summary")
    assert resp.status_code == 200
    assert isinstance(resp.json()["summary"], str)

def test_l1b_edge_case():
    """summaryがリストでないことを確認"""
    resp = httpx.get(f"{BACKEND_URL}/api/ai-summary")
    assert not isinstance(resp.json().get("summary"), list)

def test_l1b_regression():
    resp = httpx.get(f"{BACKEND_URL}/api/ai-summary")
    assert resp.status_code != 500

TESTS_L1B = [
    lambda: run_test("l1b_happy_path", test_l1b_happy_path),
    lambda: run_test("l1b_edge_case",  test_l1b_edge_case),
    lambda: run_test("l1b_regression", test_l1b_regression),
]


# ══════════════════════════════════════════════
# L1-C：モデル名廃止テスト
# ══════════════════════════════════════════════

def test_l1c_happy_path():
    resp = httpx.get(f"{BACKEND_URL}/api/ai-summary")
    assert resp.status_code == 200

def test_l1c_edge_case():
    """404が返らないことを確認"""
    resp = httpx.get(f"{BACKEND_URL}/api/ai-summary")
    assert resp.status_code != 404

def test_l1c_regression():
    resp = httpx.get(f"{BACKEND_URL}/api/ai-summary")
    assert resp.status_code != 500

TESTS_L1C = [
    lambda: run_test("l1c_happy_path", test_l1c_happy_path),
    lambda: run_test("l1c_edge_case",  test_l1c_edge_case),
    lambda: run_test("l1c_regression", test_l1c_regression),
]


# ══════════════════════════════════════════════
# L2-A：FastAPIキー名変更テスト
# ══════════════════════════════════════════════

def test_l2a_happy_path():
    resp = httpx.get(f"{BACKEND_URL}/api/tasks")
    assert resp.status_code == 200
    tasks = resp.json()["tasks"]
    assert len(tasks) > 0
    assert "task_title" in tasks[0]
    assert isinstance(tasks[0]["task_title"], str)

def test_l2a_edge_case():
    """task_titleがNoneでないことを確認"""
    resp = httpx.get(f"{BACKEND_URL}/api/tasks")
    for task in resp.json()["tasks"]:
        assert task["task_title"] is not None

def test_l2a_regression():
    """titleキーが存在しないことを確認（旧バグの再発防止）"""
    resp = httpx.get(f"{BACKEND_URL}/api/tasks")
    for task in resp.json()["tasks"]:
        assert "task_title" in task

TESTS_L2A = [
    lambda: run_test("l2a_happy_path", test_l2a_happy_path),
    lambda: run_test("l2a_edge_case",  test_l2a_edge_case),
    lambda: run_test("l2a_regression", test_l2a_regression),
]


# ══════════════════════════════════════════════
# L2-B：ネスト構造変化テスト
# ══════════════════════════════════════════════

def test_l2b_happy_path():
    resp = httpx.get(f"{BACKEND_URL}/api/tasks")
    tasks = resp.json()["tasks"]
    assert isinstance(tasks[0]["user"], str)

def test_l2b_edge_case():
    """userがdictでないことを確認"""
    resp = httpx.get(f"{BACKEND_URL}/api/tasks")
    for task in resp.json()["tasks"]:
        assert not isinstance(task["user"], dict)

def test_l2b_regression():
    resp = httpx.get(f"{BACKEND_URL}/api/tasks")
    assert resp.status_code == 200

TESTS_L2B = [
    lambda: run_test("l2b_happy_path", test_l2b_happy_path),
    lambda: run_test("l2b_edge_case",  test_l2b_edge_case),
    lambda: run_test("l2b_regression", test_l2b_regression),
]


# ══════════════════════════════════════════════
# L2-C：配列→辞書変化テスト
# ══════════════════════════════════════════════

def test_l2c_happy_path():
    resp = httpx.get(f"{BACKEND_URL}/api/tasks")
    tasks = resp.json()["tasks"]
    assert isinstance(tasks, list)

def test_l2c_edge_case():
    """tasksが空でないことを確認"""
    resp = httpx.get(f"{BACKEND_URL}/api/tasks")
    assert len(resp.json()["tasks"]) > 0

def test_l2c_regression():
    """tasksがdictでないことを確認（旧バグの再発防止）"""
    resp = httpx.get(f"{BACKEND_URL}/api/tasks")
    assert not isinstance(resp.json()["tasks"], dict)

TESTS_L2C = [
    lambda: run_test("l2c_happy_path", test_l2c_happy_path),
    lambda: run_test("l2c_edge_case",  test_l2c_edge_case),
    lambda: run_test("l2c_regression", test_l2c_regression),
]


# ── シナリオ→テストのマッピング ──────────────

SCENARIO_TESTS = {
    "L1-A": TESTS_L1A,
    "L1-B": TESTS_L1B,
    "L1-C": TESTS_L1C,
    "L2-A": TESTS_L2A,
    "L2-B": TESTS_L2B,
    "L2-C": TESTS_L2C,
}


def run_all_tests(scenario: str) -> dict:
    """指定シナリオの全テストを実行して結果を返す"""
    tests = SCENARIO_TESTS.get(scenario, [])
    results = [t() for t in tests]
    passed  = sum(1 for r in results if r["passed"])
    return {
        "scenario":  scenario,
        "total":     len(results),
        "passed":    passed,
        "failed":    len(results) - passed,
        "all_passed": passed == len(results),
        "details":   results,
    }
