from datetime import date

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .course_knowledge import CourseKnowledge, InfraiError

app = FastAPI(title="Course Knowledge Assistant")


class AnswerRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    learner_id: str = Field(min_length=1, max_length=100)
    as_of: date


class AnswerResponse(BaseModel):
    answer: str
    source_ids: list[str]


@app.post("/answers", response_model=AnswerResponse)
def answer_course_question(request: AnswerRequest) -> AnswerResponse:
    try:
        answer, source_ids = CourseKnowledge().answer(
            request.question, request.learner_id, request.as_of
        )
    except InfraiError as exc:
        status = exc.status_code if 400 <= exc.status_code < 500 else 502
        raise HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)}) from exc
    return AnswerResponse(answer=answer, source_ids=source_ids)

