"""
バグ注入スクリプト
6シナリオの注入・リセットを管理する
"""
import re
import shutil
from pathlib import Path

ROUTER_FILE  = Path("/app/routers/tasks.py")
SCHEMA_FILE  = Path("/app/schemas/task.py")
MOCK_FILE    = Path("/evaluation/mock_gemini_server.py")

# ── バックアップ管理 ──────────────────────────

def backup():
    for f in [ROUTER_FILE, SCHEMA_FILE, MOCK_FILE]:
        shutil.copy(f, f.with_suffix(".py.bak"))
    print("バックアップ完了")


def restore():
    for f in [ROUTER_FILE, SCHEMA_FILE, MOCK_FILE]:
        bak = f.with_suffix(".py.bak")
        if bak.exists():
            shutil.copy(bak, f)
    print("リストア完了")


# ── バグ注入関数 ──────────────────────────────

def inject(scenario: str):
    """指定シナリオのバグを注入する"""
    backup()

    if scenario == "L1-A":
        _inject_l1a()
    elif scenario == "L1-B":
        _inject_l1b()
    elif scenario == "L1-C":
        _inject_l1c()
    elif scenario == "L2-A":
        _inject_l2a()
    elif scenario == "L2-B":
        _inject_l2b()
    elif scenario == "L2-C":
        _inject_l2c()
    else:
        raise ValueError(f"未知のシナリオ: {scenario}")

    print(f"[{scenario}] バグ注入完了")


def _inject_l1a():
    """L1-A: Gemini APIレスポンスのキー名変更 → KeyError"""
    content = MOCK_FILE.read_text()
    content = content.replace(
        '{"text": "3件のタスクがあります。APIドキュメントの確認とPRレビューが未完了です。"}',
        '{"output": "3件のタスクがあります。APIドキュメントの確認とPRレビューが未完了です。"}'
    )
    MOCK_FILE.write_text(content)


def _inject_l1b():
    """L1-B: textフィールドをlistに変更 → TypeError"""
    content = MOCK_FILE.read_text()
    content = content.replace(
        '{"text": "3件のタスクがあります。APIドキュメントの確認とPRレビューが未完了です。"}',
        '{"text": ["3件のタスクがあります。", "APIドキュメントの確認とPRレビューが未完了です。"]}'
    )
    MOCK_FILE.write_text(content)


def _inject_l1c():
    """L1-C: 廃止モデル名を使用 → HTTPException 404"""
    content = ROUTER_FILE.read_text()
    content = content.replace(
        "models/gemini-pro:generateContent",
        "models/gemini-pro-deprecated:generateContent"
    )
    ROUTER_FILE.write_text(content)


def _inject_l2a():
    """L2-A: FastAPIレスポンスのキー名変更 → React側でundefined"""
    content = SCHEMA_FILE.read_text()
    content = content.replace("task_title: str", "title: str")
    SCHEMA_FILE.write_text(content)


def _inject_l2b():
    """L2-B: userフィールドをネスト構造に変更 → TypeError"""
    content = ROUTER_FILE.read_text()
    content = re.sub(
        r'"user": "(\w+)"',
        r'"user": {"name": "\1"}',
        content
    )
    ROUTER_FILE.write_text(content)


def _inject_l2c():
    """L2-C: tasksをlist→dictに変更 → React側で.map()エラー"""
    content = ROUTER_FILE.read_text()
    content = content.replace(
        'return {"tasks": _FAKE_TASKS}',
        'return {"tasks": {str(i): t for i, t in enumerate(_FAKE_TASKS)}}'
    )
    ROUTER_FILE.write_text(content)


# ── CLI ──────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("使い方: python inject_bug.py [L1-A|L1-B|L1-C|L2-A|L2-B|L2-C|restore]")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "restore":
        restore()
    else:
        inject(cmd)
