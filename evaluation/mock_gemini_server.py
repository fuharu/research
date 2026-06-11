import json
from http.server import HTTPServer, BaseHTTPRequestHandler

MOCK_RESPONSE = {
    "candidates": [{
        "content": {
            "parts": [{
                # L1-A 注入後：output キーでレスポンスを返す
                "output": "3件のタスクがあります。APIドキュメントの確認とPRレビューが未完了です。"
            }]
        }
    }]
}

# リフレクション用：L1-A の修正コードを返す
FIX_RESPONSE_L1A = {
    "candidates": [{
        "content": {
            "parts": [{
                "text": """エラーの原因：Gemini APIのレスポンスキーが 'text' から 'output' に変更された。
修正方針：candidates[0]["content"]["parts"][0]["output"] を参照するように変更する。
```python
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

        # L1-A 修正済み：output キーを参照する
        text = data["candidates"][0]["content"]["parts"][0]["output"]
        summary = str(text)
        return {"summary": summary}

    except KeyError as e:
        raise HTTPException(status_code=500, detail=f"Gemini APIレスポンスのパースに失敗: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```
"""
            }]
        }
    }]
}

FIX_RESPONSE_L1B = {
    "candidates": [{"content": {"parts": [{"text": """
エラーの原因：要約テキストの型が変化しうるため、文字列化処理が必要。
修正方針：output を取得し、list の場合は先頭要素を取り出して文字列化する。
```python
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

        text = data["candidates"][0]["content"]["parts"][0]["output"]
        if isinstance(text, list):
            text = text[0]
        summary = str(text)

        return {"summary": summary}
    except KeyError as e:
        raise HTTPException(status_code=500, detail=f"Gemini APIレスポンスのパースに失敗: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```
"""}]}}]
}

FIX_RESPONSE_L1C = {
    "candidates": [{"content": {"parts": [{"text": """
エラーの原因：gemini-pro-deprecated は廃止されたモデル名。
修正方針：gemini-pro に戻す。
```python
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

        text = data["candidates"][0]["content"]["parts"][0]["output"]
        summary = str(text)
        return {"summary": summary}
    except KeyError as e:
        raise HTTPException(status_code=500, detail=f"Gemini APIレスポンスのパースに失敗: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```
"""}]}}]
}

FIX_RESPONSE_L2A = {
    "candidates": [{"content": {"parts": [{"text": """
エラーの原因：レスポンスのキー名が title になっている。
修正方針：task_title に戻す。
```python
from pydantic import BaseModel

class TaskResponse(BaseModel):
    task_title: str
    task_done: bool
    user: str

class TaskListResponse(BaseModel):
    tasks: list[TaskResponse]

class AISummaryResponse(BaseModel):
    summary: str
```
"""}]}}]
}

FIX_RESPONSE_L2B = {
    "candidates": [{"content": {"parts": [{"text": """
エラーの原因：user フィールドが辞書になっている。
修正方針：user を文字列のまま返すように戻す。
```python
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

        text = data["candidates"][0]["content"]["parts"][0]["output"]
        summary = str(text)
        return {"summary": summary}
    except KeyError as e:
        raise HTTPException(status_code=500, detail=f"Gemini APIレスポンスのパースに失敗: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```
"""}]}}]
}

FIX_RESPONSE_L2C = {
    "candidates": [{"content": {"parts": [{"text": """
エラーの原因：tasks が dict になっている。
修正方針：list を返すように戻す。
```python
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

        text = data["candidates"][0]["content"]["parts"][0]["output"]
        summary = str(text)
        return {"summary": summary}
    except KeyError as e:
        raise HTTPException(status_code=500, detail=f"Gemini APIレスポンスのパースに失敗: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```
"""}]}}]
}


class MockGeminiHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode()

        is_fix_request = any(kw in body for kw in [
            "エラーを修正", "エラーの根本原因", "修正後のファイル全体"
        ])

        if is_fix_request:
            # シナリオをボディから判別（エラーメッセージ優先）
            if "can only concatenate str" in body or "L1-B" in body:
                response = FIX_RESPONSE_L1B
            elif "deprecated" in body or "L1-C" in body:
                response = FIX_RESPONSE_L1C
            elif "task_title" in body or "L2-A" in body:
                response = FIX_RESPONSE_L2A
            elif "user is dict" in body or "L2-B" in body:
                response = FIX_RESPONSE_L2B
            elif "object is not iterable" in body or "L2-C" in body:
                response = FIX_RESPONSE_L2C
            elif "output" in body or "L1-A" in body:
                response = FIX_RESPONSE_L1A
            else:
                response = FIX_RESPONSE_L1A  # フォールバック
        else:
            response = MOCK_RESPONSE

        if "gemini-pro-deprecated" in self.path:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error": "model not found"}')
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(response).encode())

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", 9000), MockGeminiHandler)
    print("Mock Gemini server running on port 9000")
    server.serve_forever()
