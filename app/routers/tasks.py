import os
import httpx
from fastapi import APIRouter, HTTPException
from schemas.task import TaskListResponse, TaskResponse, AISummaryResponse

router = APIRouter(prefix="/api", tags=["tasks"])

GEMINI_URL = os.getenv("MOCK_GEMINI_URL", "https://generativelanguage.googleapis.com")
USE_MOCK = os.getenv("USE_MOCK_GEMINI", "true").lower() == "true"

_FAKE_TASKS = [
    {"task_title": "APIドキュメントを読む", "task_done": False, "user": "Alice"},
    {"task_title": "テストを書く",          "task_done": True,  "user": "Bob"},
    {"task_title": "PRをレビューする",      "task_done": False, "user": "Alice"},
]

@router.get("/tasks", response_model=TaskListResponse)
def get_tasks():
    return {"tasks": _FAKE_TASKS}

@router.post("/tasks", response_model=TaskResponse)
def create_task(task: TaskResponse):
    _FAKE_TASKS.append(task.dict())
    return task

@router.get("/ai-summary", response_model=AISummaryResponse)
async def get_ai_summary():
    prompt = f"以下のタスク一覧を1文で要約してください：{_FAKE_TASKS}"
    try:
        if USE_MOCK:
            url = f"{GEMINI_URL}/v1beta/models/gemini-pro:generateContent"
        else:
            api_key = os.getenv("GEMINI_API_KEY")
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={api_key}"

        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json={"contents": [{"parts": [{"text": prompt}]}]})
            resp.raise_for_status()
            data = resp.json()

        parts = data["candidates"][0]["content"]["parts"][0]
        text = parts.get("output", parts.get("text", ""))
        if isinstance(text, list):
            text = text[0]
        summary = str(text)

        return {"summary": summary}
    except KeyError as e:
        raise HTTPException(status_code=500, detail=f"Gemini APIレスポンスのパースに失敗: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))