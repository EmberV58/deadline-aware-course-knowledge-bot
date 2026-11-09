from datetime import date

from src.course_knowledge import CourseRecord, prioritize_deadlines


def test_imminent_deadline_wins_an_equal_relevance_tie() -> None:
    policy = CourseRecord("submission-policy", "Submit in the workspace.", "course_delivery")
    deadline = CourseRecord(
        "python-capstone-deadline",
        "The capstone is due September 29.",
        "learner_deadline",
        date(2026, 9, 29),
    )

    ordered = prioritize_deadlines(
        [(policy, 0.91), (deadline, 0.91)],
        as_of=date(2026, 9, 27),
    )

    assert [record.record_id for record in ordered] == [
        "python-capstone-deadline",
        "submission-policy",
    ]



def test_in_memory_retrieval_needs_no_persistent_vector_client() -> None:
    from src.course_knowledge import CourseKnowledge, SEED_RECORDS

    knowledge = CourseKnowledge.__new__(CourseKnowledge)
    knowledge.in_memory = True
    knowledge.embed = lambda texts: [[1.0, 0.0] for _ in texts]

    records = knowledge.retrieve("When is the capstone due?", date(2026, 9, 27))

    assert records[0].record_id == "python-capstone-deadline"
    assert {record.record_id for record in records} == {record.record_id for record in SEED_RECORDS}
