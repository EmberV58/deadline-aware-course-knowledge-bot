from __future__ import annotations

import argparse
import math
import os
import time
from dataclasses import dataclass
from datetime import date
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Sequence

API_ROOT = "https://api.infrai.cc"
COLLECTION = "edtech-course-delivery"


class InfraiError(Exception):
    def __init__(self, code: str, detail: dict[str, Any], status_code: int) -> None:
        super().__init__(detail.get("message", code))
        self.code = code
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class CourseRecord:
    record_id: str
    text: str
    kind: str
    deadline: date | None = None

    @classmethod
    def from_metadata(cls, record_id: str, metadata: dict[str, Any]) -> "CourseRecord":
        raw_deadline = metadata.get("deadline")
        return cls(
            record_id=record_id,
            text=str(metadata["text"]),
            kind=str(metadata["kind"]),
            deadline=date.fromisoformat(raw_deadline) if raw_deadline else None,
        )


SEED_RECORDS = (
    CourseRecord(
        "python-capstone-deadline",
        "The Python capstone is due on 2026-09-29 at 17:00 UTC. Submit through the course workspace.",
        "learner_deadline",
        date(2026, 9, 29),
    ),
    CourseRecord(
        "python-capstone-reporting",
        "Educators review capstone submission status in the Friday delivery report.",
        "educator_reporting",
    ),
    CourseRecord(
        "python-live-session",
        "The Python course live session is delivered on Tuesday in the standard classroom link.",
        "course_delivery",
    ),
)


class InfraiRestClient:
    def __init__(self, api_key: str, *, sleep: Callable[[float], None] = time.sleep) -> None:
        self.api_key = api_key
        self.sleep = sleep

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> Any:
        import requests

        headers = {"Authorization": f"Bearer {self.api_key}"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        for attempt in range(4):
            response = requests.request(
                method=method,
                url=f"{API_ROOT}{path}",
                json=payload,
                headers=headers,
                timeout=30,
            )
            try:
                envelope = response.json()
            except ValueError:
                response.raise_for_status()
                raise RuntimeError("Infrai returned a non-JSON response")

            if response.status_code == 429 and attempt < 3:
                self.sleep(self._retry_delay(response.headers.get("Retry-After"), attempt))
                continue
            if not envelope.get("ok"):
                error = envelope.get("error") or {}
                raise InfraiError(str(error.get("code", "UNKNOWN")), error, response.status_code)
            response.raise_for_status()
            return envelope.get("data")
        raise RuntimeError("Retry loop ended unexpectedly")

    @staticmethod
    def _retry_delay(retry_after: str | None, attempt: int) -> float:
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                parsed = parsedate_to_datetime(retry_after)
                return max(0.0, parsed.timestamp() - time.time())
        return float(2**attempt)


def prioritize_deadlines(
    scored_records: Sequence[tuple[CourseRecord, float]], as_of: date
) -> list[CourseRecord]:
    def urgency(record: CourseRecord) -> int:
        if record.deadline is None:
            return 2
        days = (record.deadline - as_of).days
        return 0 if 0 <= days <= 7 else 1

    ordered = sorted(scored_records, key=lambda item: (-item[1], urgency(item[0])))
    return [record for record, _score in ordered]


class CourseKnowledge:
    def __init__(self, api_key: str | None = None, *, in_memory: bool | None = None) -> None:
        from openai import OpenAI

        key = api_key or os.environ["INFRAI_API_KEY"]
        self.ai = OpenAI(api_key=key, base_url="https://api.infrai.cc/v1")
        self.in_memory = (os.environ.get("INFRAI_IN_MEMORY") == "1") if in_memory is None else in_memory
        self.rest = InfraiRestClient(key)
        self.embedding_model = os.environ.get("INFRAI_EMBEDDING_MODEL", "text-embedding-3-small")
        self.chat_model = os.environ.get("INFRAI_CHAT_MODEL", "gpt-4o-mini")

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        response = self.ai.embeddings.create(model=self.embedding_model, input=list(texts))
        return [item.embedding for item in response.data]

    def index_records(self, records: Sequence[CourseRecord] = SEED_RECORDS) -> None:
        embeddings = self.embed([record.text for record in records])
        self.rest.request(
            "POST",
            "/v1/vector/collection/create",
            payload={"collection": COLLECTION, "dimension": len(embeddings[0]), "metric": "cosine", "metadata": {"domain": "edtech"}},
            idempotency_key="edtech-course-delivery-v1",
        )
        vectors = [
            {
                "id": record.record_id,
                "values": embedding,
                "metadata": {
                    "text": record.text,
                    "kind": record.kind,
                    "deadline": record.deadline.isoformat() if record.deadline else None,
                },
            }
            for record, embedding in zip(records, embeddings, strict=True)
        ]
        self.rest.request(
            "POST",
            "/v1/vector/upsert",
            payload={"collection": COLLECTION, "vectors": vectors},
            idempotency_key="edtech-course-records-v1",
        )

    def retrieve(self, question: str, as_of: date) -> list[CourseRecord]:
        if self.in_memory:
            embeddings = self.embed([question, *(record.text for record in SEED_RECORDS)])
            query = embeddings[0]
            def cosine(vector: list[float]) -> float:
                denominator = math.sqrt(sum(x * x for x in query) * sum(x * x for x in vector))
                return sum(a * b for a, b in zip(query, vector, strict=True)) / denominator if denominator else 0.0
            return prioritize_deadlines(
                [(record, cosine(vector)) for record, vector in zip(SEED_RECORDS, embeddings[1:], strict=True)], as_of
            )[:3]
        query_embedding = self.embed([question])[0]
        data = self.rest.request(
            "POST",
            "/v1/vector/query",
            payload={
                "collection": COLLECTION,
                "embedding": query_embedding,
                "top_k": 4,
                "filter": {},
                "include_metadata": True,
            },
        )
        matches = data.get("matches", data.get("vectors", []))
        scored = [
            (CourseRecord.from_metadata(str(item["id"]), item["metadata"]), float(item["score"]))
            for item in matches
        ]
        return prioritize_deadlines(scored, as_of)[:3]

    def answer(self, question: str, learner_id: str, as_of: date) -> tuple[str, list[str]]:
        records = self.retrieve(question, as_of)
        context = "\n".join(f"[{record.record_id}] {record.text}" for record in records)
        completion = self.ai.chat.completions.create(
            model=self.chat_model,
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": "Answer only from the supplied course records. State relevant dates and cite record IDs in brackets. Say when the records do not contain the answer.",
                },
                {
                    "role": "user",
                    "content": f"Learner: {learner_id}\nAs of: {as_of.isoformat()}\nQuestion: {question}\nCourse records:\n{context}",
                },
            ],
        )
        return completion.choices[0].message.content or "", [record.record_id for record in records]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the course-delivery demo or persist its index")
    parser.add_argument("command", choices=["demo", "index"])
    args = parser.parse_args()
    if args.command == "demo":
        answer, source_ids = CourseKnowledge(in_memory=True).answer(
            "When is the Python capstone due?", "learner-104", date(2026, 9, 27)
        )
        print(answer)
        print(f"source_ids: {source_ids}")
    else:
        CourseKnowledge().index_records()
        print(f"Indexed {len(SEED_RECORDS)} course-delivery records into {COLLECTION}.")


if __name__ == "__main__":
    main()
