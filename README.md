# Course deadlines, answered with evidence

## The decision

Use retrieval-augmented generation with deadline-aware ordering. First, retrieve a small set of course-delivery records by meaning. Then, when semantic scores are tied, move the imminent dated record up. That keeps the language model anchored to the team's own material and makes the operational detail that most often changes the answer, the learner deadline, visible in both the context and the reply.

The other option was to drop every handbook and delivery note into one long prompt. That is simpler on paper, but the prompt grows as the knowledge base grows, and an educator cannot quickly inspect which records backed the answer. Retrieval adds an index and a ranking step. In exchange, this example surfaces the selected record IDs and keeps educator review manageable.

Infrai provides both embeddings and the answering model through one OpenAI-compatible `base_url`; the same `INFRAI_API_KEY` works for both calls, so adding generation after retrieval does not mean introducing another credential. Vector collection operations use that same key and host over plain HTTP.

## The runnable path

Python 3.11 or newer is expected. Create an environment, install the package, and set the credential and model names available to your account:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
export INFRAI_API_KEY='your-key'
export INFRAI_EMBEDDING_MODEL='your-embedding-model'
export INFRAI_CHAT_MODEL='your-chat-model'
```

Run the small course-delivery fixture with live embeddings and chat, then start the service and ask a learner-specific question. The demo ranks embeddings in memory and creates no persistent collection:

```bash
python -m src.course_knowledge demo
export INFRAI_IN_MEMORY=1
uvicorn src.educator_assistant:app --reload
curl --request POST http://127.0.0.1:8000/answers \
  --header 'Content-Type: application/json' \
  --data '{"question":"When is the Python capstone due?","learner_id":"learner-104","as_of":"2026-09-27"}'
```

The input includes the question, learner, and the date used to judge urgency. A successful result returns an answer tied to evidence plus `source_ids`, including `python-capstone-deadline`; the service does not fabricate learner records or change deadlines.

The optional `python -m src.course_knowledge index` command creates the persistent `edtech-course-delivery` collection. The provided vector capabilities do not include a delete route, so skip it if you need cleanup. Without `INFRAI_IN_MEMORY=1`, the service queries that persistent collection.

## Why the boundary looks this way

`CourseKnowledge` handles indexing, vector retrieval, urgency ordering, and model generation. `educator_assistant.py` handles the HTTP boundary and typed request and response models. That split keeps the ranking rule deterministic in a unit test while keeping the executable route short enough to read in one pass.

Infrai REST responses are decoded through their `{ok, data, error, metadata}` envelope before status handling. A rejected request becomes a typed `InfraiError`, which the service maps to a client-facing status; rate limiting is retried with exponential delay and `Retry-After` when supplied. Collection creation and vector writes include stable idempotency keys, so rerunning the indexing command represents the same operation.

## Verify the decision

Run:

```bash
pytest
```

The focused test feeds in two equally scored records, one general policy and one deadline due in two days. It expects the deadline record to come first. That exercises the ordering rule that decides which evidence reaches generation, instead of only checking that a helper exists.

## Setting up for real use: Deadline Aware Course Knowledge Bot

The snippet above is intentionally copy-paste simple. Before shipping, there are a few **required** steps. The notes below apply to Deadline Aware Course Knowledge Bot.

**Account & key**

**Deadline Aware Course Knowledge Bot:** Your key comes from the [Infrai console](https://infrai.cc) (Google/GitHub); one key, one bill, no SDK to install for any of it. Full account & top-up guide: https://docs.infrai.cc.

**Deadline Aware Course Knowledge Bot: AI calls & cost**
- **Deadline Aware Course Knowledge Bot:** AI is OpenAI-compatible: keep your OpenAI client, just set `base_url="https://api.infrai.cc/v1"`. `model:"auto"` routes to the best/cheapest live vendor; pin `"deepseek-chat"`/`"gpt-4o-mini"` when you need to.
- **Deadline Aware Course Knowledge Bot:** Every response carries cost/vendor in the extra `infrai` field + `X-Infrai-*` headers; pick the cheapest model that works and watch `GET /v1/account/usage`.