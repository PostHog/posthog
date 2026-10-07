import asyncio

import unittest
from unittest.mock import AsyncMock, patch

from parameterized import parameterized

from products.workflows.evals.scorers import EmailProse, EmailStructure


class TestEmailProse(unittest.TestCase):
    @parameterized.expand(
        [
            ("not_a_list", "Copy here"),
            ("non_objects", [None, "email"]),
        ]
    )
    def test_malformed_drafts_fail_without_paid_judging(self, name: str, emails: object) -> None:
        with patch("autoevals.llm.LLMClassifier._run_eval_async", new_callable=AsyncMock) as judge:
            score = asyncio.run(EmailProse().eval_async(output={"emails": emails}, expected={}))
        self.assertEqual(score.score, 0.0)
        judge.assert_not_called()


class TestEmailStructure(unittest.TestCase):
    @parameterized.expand(
        [
            ("html", {"html": '<p>Upload a file.</p><a href="https://example.com/upload">Upload</a>'}),
            (
                "design",
                {
                    "design": {
                        "body": {
                            "rows": [
                                {
                                    "columns": [
                                        {
                                            "contents": [
                                                {"type": "text", "values": {"text": "<p>Upload a file.</p>"}},
                                                {
                                                    "type": "button",
                                                    "values": {
                                                        "text": "Upload",
                                                        "href": {
                                                            "name": "web",
                                                            "values": {
                                                                "href": "https://example.com/upload",
                                                                "target": "_blank",
                                                            },
                                                        },
                                                    },
                                                },
                                            ]
                                        }
                                    ]
                                }
                            ]
                        }
                    }
                },
            ),
        ]
    )
    def test_accepts_editable_or_html_email(self, name: str, body: dict) -> None:
        score = EmailStructure().eval(
            output={
                "emails": [
                    {
                        "subject": "Your first file in CloudShelf",
                        "text": "Keep a file handy on any device. Upload it at https://example.com/upload",
                        **body,
                    }
                ]
            },
            expected={"email_structure": {"count": 1, "cta_urls": ["https://example.com/upload"]}},
        )
        self.assertEqual(score.score, 1.0)

    @parameterized.expand(
        [
            ("empty_subject", {"subject": ""}),
            ("long_subject", {"subject": "x" * 81}),
            ("short_body", {"text": "Placeholder https://example.com/upload"}),
            (
                "markup_text",
                {"text": "<p>Keep a file handy on any device. Upload it at https://example.com/upload</p>"},
            ),
            ("missing_rich_body", {"html": ""}),
            ("missing_cta", {"text": "Keep a file handy on any device. Your folder is ready to use."}),
            ("wrong_count", None),
            ("bare_url_body", {"html": "https://example.com/upload"}),
            ("fake_design", {"html": "", "design": {"url": "https://example.com/upload"}}),
            (
                "wrong_url_prefix",
                {
                    "text": "Keep a file handy on any device. Upload it at https://example.com/upload-wrong",
                    "html": '<a href="https://example.com/upload-wrong">Upload</a>',
                },
            ),
        ]
    )
    def test_rejects_incomplete_drafts(self, name: str, patch: dict | None) -> None:
        email = {
            "subject": "Your first file in CloudShelf",
            "text": "Keep a file handy on any device. Upload it at https://example.com/upload",
            "html": '<p>Upload a file.</p><a href="https://example.com/upload">Upload</a>',
        }
        score = EmailStructure().eval(
            output={"emails": [{**email, **patch}] if patch is not None else []},
            expected={"email_structure": {"count": 1, "cta_urls": ["https://example.com/upload"]}},
        )
        self.assertEqual(score.score, 0.0)

    def test_sequence_uses_each_steps_destination(self) -> None:
        email = {
            "subject": "Your first file in CloudShelf",
            "text": "Keep a file handy on any device. Upload it at https://example.com/upload",
            "html": '<p>Upload a file.</p><a href="https://example.com/upload">Upload</a>',
        }
        score = EmailStructure().eval(
            output={"emails": [email, email]},
            expected={
                "email_structure": {
                    "count": 2,
                    "cta_urls": [
                        "https://example.com/upload",
                        "https://example.com/share",
                    ],
                }
            },
        )
        self.assertEqual(score.score, 0.0)
