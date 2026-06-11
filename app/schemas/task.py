from pydantic import BaseModel


# ──────────────────────────────────────────────
# ★ 修正可能な層（L2-A/B/C バグ注入対象）
#
# inject_bug.py がこのファイルのフィールド名・型を書き換える
# ──────────────────────────────────────────────

class TaskResponse(BaseModel):
    task_title: str       # L2-A: "title" に変更するとReact側でundefined
    task_done: bool
    user: str             # L2-B: {"name": "Alice"} のネスト構造に変更可能


class TaskListResponse(BaseModel):
    tasks: list[TaskResponse]   # L2-C: list → dict に変更するとReact側で.map()エラー


class AISummaryResponse(BaseModel):
    summary: str
