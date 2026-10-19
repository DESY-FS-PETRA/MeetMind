from __future__ import annotations

import unittest

from app.ai.structured_enricher import StructuredMeetingEnricher
from app.schemas.summary import ActionItem, MeetingSummaryContent


class StructuredMeetingEnricherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.enricher = StructuredMeetingEnricher()

    def test_recovers_explicit_decision_and_named_action(self) -> None:
        content = MeetingSummaryContent(
            summary="A short summary.",
            key_points=[],
            decisions=[],
            action_items=[],
            open_questions=[],
        )
        transcript = (
            "The team agreed to use Ollama for local meeting summarization. "
            "Vahid will integrate the Ollama endpoint into FastAPI before Friday."
        )

        result = self.enricher.enrich(content, transcript)

        self.assertEqual(
            result.decisions,
            ["Use Ollama for local meeting summarization."],
        )
        self.assertEqual(len(result.action_items), 1)
        self.assertEqual(result.action_items[0].owner, "Vahid")
        self.assertEqual(result.action_items[0].deadline, "Friday")
        self.assertEqual(
            result.action_items[0].task,
            "Integrate the Ollama endpoint into FastAPI.",
        )

    def test_fills_missing_owner_and_deadline_without_duplicating_task(self) -> None:
        content = MeetingSummaryContent(
            summary="A short summary.",
            key_points=[],
            decisions=[],
            action_items=[
                ActionItem(
                    task="Integrate the Ollama endpoint into FastAPI.",
                    owner=None,
                    deadline=None,
                )
            ],
            open_questions=[],
        )
        transcript = "Vahid will integrate the Ollama endpoint into FastAPI by Friday."

        result = self.enricher.enrich(content, transcript)

        self.assertEqual(len(result.action_items), 1)
        self.assertEqual(result.action_items[0].owner, "Vahid")
        self.assertEqual(result.action_items[0].deadline, "Friday")

    def test_does_not_treat_team_technology_choice_as_action_item(self) -> None:
        content = MeetingSummaryContent(
            summary="A short summary.",
            key_points=[],
            decisions=[],
            action_items=[],
            open_questions=[],
        )
        transcript = "We will use PostgreSQL for persistent storage."

        result = self.enricher.enrich(content, transcript)

        self.assertEqual(result.decisions, ["Use PostgreSQL for persistent storage."])
        self.assertEqual(result.action_items, [])

    def test_does_not_assign_a_noun_phrase_as_owner(self) -> None:
        content = MeetingSummaryContent(
            summary="A short summary.",
            key_points=[],
            decisions=[],
            action_items=[],
            open_questions=[],
        )
        transcript = "The embedding model will be selected in a future phase."

        result = self.enricher.enrich(content, transcript)

        self.assertEqual(result.action_items, [])

    def test_does_not_invent_items_from_neutral_sentences(self) -> None:
        content = MeetingSummaryContent(
            summary="A short summary.",
            key_points=[],
            decisions=[],
            action_items=[],
            open_questions=[],
        )
        transcript = "The team reviewed the current transcription quality."

        result = self.enricher.enrich(content, transcript)

        self.assertEqual(result.decisions, [])
        self.assertEqual(result.action_items, [])


if __name__ == "__main__":
    unittest.main()
