# -*- coding: utf-8 -*-
"""
A方式の基盤：研究用agentコンテナから BugsInPy(別コンテナ) の checkout を操作する。
- ファイル: /bench_workspace/<proj>/... を直接 read/write（共有ボリューム）
- テスト  : docker exec で bugsinpy コンテナの bugsinpy-test を実行し pass/fail 判定
前提: bugsinpy コンテナ起動中（--name bugsinpy）、対象バグが checkout 済み。
スモーク実行: docker compose run --rm agent python /evaluation/bench_bugsinpy.py
"""
import os
from pathlib import Path

BENCH_WS           = os.getenv("BENCH_WS", "/bench_workspace")
BUGSINPY_CONTAINER = os.getenv("BUGSINPY_CONTAINER", "bugsinpy")
BUGSINPY_WS        = os.getenv("BUGSINPY_WS", "/home/workspace")

def project_dir(proj):  return f"{BENCH_WS}/{proj}"
def read_file(path):    return Path(path).read_text(encoding="utf-8", errors="replace")
def write_file(path, content): Path(path).write_text(content, encoding="utf-8")

def run_bugsinpy_test(proj):
    """bugsinpy コンテナ内で bugsinpy-test を実行し {all_passed, out} を返す。"""
    import docker
    client = docker.from_env()
    c = client.containers.get(BUGSINPY_CONTAINER)
    cmd = ("export PATH=$PATH:/home/bugsinpy/framework/bin; "
           f"cd {BUGSINPY_WS}/{proj} && bugsinpy-test 2>&1")
    res = c.exec_run(["bash", "-lc", cmd])
    out = res.output.decode("utf-8", "replace")
    lines = [l.strip() for l in out.splitlines()]
    failed = any(l.startswith("FAILED") for l in lines)
    okline = any(l == "OK" or l.startswith("OK ") for l in lines)
    return {"all_passed": (okline and not failed), "out": out}

if __name__ == "__main__":
    proj = os.getenv("PROJ", "youtube-dl")
    pdir = project_dir(proj)
    print("BENCH_WS:", BENCH_WS, "/ proj dir exists:", Path(pdir).exists())
    tgt = f"{pdir}/youtube_dl/extractor/common.py"
    print("target readable:", Path(tgt).exists())
    print("running bugsinpy-test via docker exec ...")
    try:
        r = run_bugsinpy_test(proj)
        print("all_passed:", r["all_passed"])
        print("---- tail ----\n", r["out"][-700:])
    except Exception as e:
        import traceback; traceback.print_exc()
        print("!! docker exec 失敗:", e)
