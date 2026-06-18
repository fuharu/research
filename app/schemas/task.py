from pydantic import BaseModel


class TaskResponse(BaseModel):
    task_title: str
    task_done: bool
    user: str


class TaskListResponse(BaseModel):
    tasks: list[TaskResponse]


class AISummaryResponse(BaseModel):
    summary: str
