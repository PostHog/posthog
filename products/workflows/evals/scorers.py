"""Scorers for the email domain setup eval suite.

They grade outcomes rather than the path the agent took, so a reordered or extended
setup flow keeps passing: which senders the project holds after the run, what the final
message hands the person, and a few rules the skill exists to enforce.

Every scorer reads its per-case parameters from ``expected`` under its own ``_name()``
and returns ``score=None`` when its key is absent, so one scorer list spans the suite.
"""

from __future__ import annotations

import re
import html
import asyncio
from typing import Any

from posthog.models.integration import Integration

from products.posthog_ai.eval_harness.log_parser import LogParser, ToolCall
from products.posthog_ai.eval_harness.scorers import (
    BINARY_CHOICE_SCORES,
    JUDGE_MODEL,
    AsyncOnlyScorerMixin,
    JudgedScorer,
)
from products.posthog_ai.eval_harness.scorers.contract import Score, Scorer
from products.workflows.evals.simulated_email_domains import DOMAIN_CONNECT_SYNC_UX

__all__ = [
    "APPLY_URL_PATH",
    "AvoidedTool",
    "BoundedVerifyPolling",
    "FinalMessageJudge",
    "FinalMessageMentions",
    "MergedSpfRecord",
    "RecordsHandoffJudge",
    "SendersInProject",
    "SharedApplyUrl",
]

APPLY_URL_TOOL = "integrations-domain-connect-apply-url-create"
VERIFY_TOOL = "integrations-email-verify-create"
APPLY_URL_PATH = f"{DOMAIN_CONNECT_SYNC_UX}/v2/domainTemplates/providers/posthog.com/"
APPLY_URL = re.compile(re.escape(APPLY_URL_PATH) + r"[^\s\"'\\)>\]]+")
SPF_RECORD = re.compile(r"v=spf1[^\n`\"'|]*", re.IGNORECASE)
SPF_ALL_MECHANISM = re.compile(r"^[~?+-]?all$", re.IGNORECASE)


def _spec(expected: dict | None, scorer_name: str) -> dict | None:
    spec = (expected or {}).get(scorer_name)
    return spec if isinstance(spec, dict) else None


def _parser(output: dict | None) -> LogParser | None:
    raw_log = (output or {}).get("raw_log")
    if not raw_log:
        return None
    return LogParser.cached(raw_log, initial_prompt=(output or {}).get("prompt", "") or "")


def _successful(parser: LogParser, name: str) -> list[ToolCall]:
    return [call for call in parser.get_tool_calls(name) if not call.is_error]


def _final_message(output: dict | None) -> str:
    return (output or {}).get("last_message") or ""


def _skip(name: str, reason: str) -> Score:
    return Score(name=name, score=None, metadata={"reason": reason})


def _missing_log(name: str) -> Score:
    return Score(name=name, score=0.0, metadata={"reason": "No raw log"})


def read_senders(team_id: int) -> dict[str, dict[str, Any]]:
    return {
        integration.integration_id: integration.config
        for integration in Integration.objects.filter(team_id=team_id, kind="email")
    }


class SendersInProject(AsyncOnlyScorerMixin, Scorer):
    """Binary: does the project hold exactly the expected senders, configured as expected?

    Reads the database, so a sender created through any path counts, and so does a wrong
    address or a duplicate the agent left behind. Per sender, each rule pins a config value,
    such as ``verified`` or ``mail_from_subdomain``, and a ``<key>_not`` rule rules one out.
    """

    def _name(self) -> str:
        return "senders_in_project"

    async def _run_eval_async(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        spec = _spec(expected, self._name())
        if spec is None:
            return _skip(self._name(), "Not applicable to this case")
        team_id = ((output or {}).get("seed") or {}).get("team_id")
        if not team_id:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No team id in the seed"})

        senders = await asyncio.to_thread(read_senders, team_id)
        wanted: dict[str, dict[str, Any]] = spec.get("senders", {})
        problems = [
            *(f"missing {address}" for address in wanted.keys() - senders.keys()),
            *(f"unexpected {address}" for address in senders.keys() - wanted.keys()),
            *(
                problem
                for address, rules in wanted.items()
                if address in senders
                for problem in self._config_problems(address, senders[address], rules)
            ),
        ]
        if problems:
            return Score(name=self._name(), score=0.0, metadata={"problems": problems})
        return Score(name=self._name(), score=1.0, metadata={"senders": sorted(senders)})

    def _config_problems(self, address: str, config: dict[str, Any], rules: dict[str, Any]) -> list[str]:
        problems = []
        for rule, value in rules.items():
            key = rule.removesuffix("_not")
            if rule != key and config.get(key) == value:
                problems.append(f"{address} has {key}={value!r}, which this case rules out")
            elif rule == key and config.get(key) != value:
                problems.append(f"{address} has {key}={config.get(key)!r}, expected {value!r}")
        return problems


class AvoidedTool(Scorer):
    """Binary: did no call to any of ``expected.tools`` succeed? A refused attempt passes."""

    def _name(self) -> str:
        return "avoided_tool"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        spec = _spec(expected, self._name())
        if spec is None:
            return _skip(self._name(), "Not applicable to this case")
        parser = _parser(output)
        if parser is None:
            return _missing_log(self._name())
        called = sorted(tool for tool in spec.get("tools", []) if _successful(parser, tool))
        return Score(name=self._name(), score=0.0 if called else 1.0, metadata={"called": called})


class FinalMessageMentions(Scorer):
    """Binary: does the final message contain every value in ``expected.values``?

    Record values are exact strings a person has to copy into their DNS host, so a
    summary that paraphrases or truncates one hands over a record that cannot verify.
    """

    def _name(self) -> str:
        return "final_message_mentions"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        spec = _spec(expected, self._name())
        if spec is None:
            return _skip(self._name(), "Not applicable to this case")
        message = _final_message(output)
        missing = [value for value in spec.get("values", []) if value not in message]
        return Score(name=self._name(), score=0.0 if missing else 1.0, metadata={"missing": missing})


class MergedSpfRecord(Scorer):
    """Binary: does one SPF record in the final message carry every include in ``expected.includes``?

    A domain can publish only one SPF record, so handing over a second one breaks the mail
    the existing include authorizes. Receivers stop reading at the ``all`` mechanism, so an
    include after it authorizes nothing. Which host the record goes on is the judge's call.
    """

    def _name(self) -> str:
        return "merged_spf_record"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        spec = _spec(expected, self._name())
        if spec is None:
            return _skip(self._name(), "Not applicable to this case")
        includes = {include.lower() for include in spec.get("includes", [])}
        records = SPF_RECORD.findall(_final_message(output))
        merged = [record for record in records if includes <= self._effective_mechanisms(record)]
        return Score(name=self._name(), score=1.0 if merged else 0.0, metadata={"spf_records": records})

    def _effective_mechanisms(self, record: str) -> set[str]:
        mechanisms: set[str] = set()
        for term in record.lower().split()[1:]:
            if SPF_ALL_MECHANISM.match(term):
                break
            mechanisms.add(term)
        return mechanisms


class SharedApplyUrl(Scorer):
    """Binary: does the final message carry the complete URL a successful apply-url call returned?

    Only the person can approve the change at their DNS host, so a URL that stays in a
    tool result helps nobody, and a shortened one fails its signature check.
    """

    def _name(self) -> str:
        return "shared_apply_url"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        if _spec(expected, self._name()) is None:
            return _skip(self._name(), "Not applicable to this case")
        parser = _parser(output)
        if parser is None:
            return _missing_log(self._name())
        returned = {url for call in _successful(parser, APPLY_URL_TOOL) for url in APPLY_URL.findall(call.output)}
        if not returned:
            return Score(name=self._name(), score=0.0, metadata={"reason": f"No URL from a {APPLY_URL_TOOL} call"})
        message = html.unescape(_final_message(output))
        shared = any(url in message for url in returned)
        return Score(name=self._name(), score=1.0 if shared else 0.0, metadata={"url_in_message": shared})


class BoundedVerifyPolling(Scorer):
    """Binary: did the agent call verify at most ``expected.max_calls`` times?

    Each verify call queries DNS and the email provider. When the records still wait on the
    person, or a permission error repeats, more calls cannot change the answer.
    """

    def _name(self) -> str:
        return "bounded_verify_polling"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        spec = _spec(expected, self._name())
        if spec is None:
            return _skip(self._name(), "Not applicable to this case")
        parser = _parser(output)
        if parser is None:
            return _missing_log(self._name())
        calls = len(parser.get_tool_calls(VERIFY_TOOL))
        return Score(name=self._name(), score=1.0 if calls <= spec["max_calls"] else 0.0, metadata={"calls": calls})


class FinalMessageJudge(JudgedScorer):
    """Judge one yes/no question about the final message. ``name`` is the ``expected`` key that opts a case in."""

    def __init__(self, *, name: str, question: str, **kwargs: Any) -> None:
        super().__init__(
            name=name,
            prompt_template=self._prompt_template(question),
            choice_scores=BINARY_CHOICE_SCORES,
            model=JUDGE_MODEL,
            max_completion_tokens=256,
            **kwargs,
        )

    def _prompt_template(self, question: str) -> str:
        return f"{question}\n\n<message>{{{{output.last_message}}}}</message>\n\nAnswer `yes` or `no`."

    def _prepare(self, output: dict | None, expected: dict | None) -> dict[str, Any] | Score:
        if _spec(expected, self._name()) is None:
            return _skip(self._name(), "Not applicable to this case")
        if not _final_message(output):
            return Score(name=self._name(), score=0.0, metadata={"reason": "No final message"})
        return {"output": {"last_message": _final_message(output)}}


class RecordsHandoffJudge(FinalMessageJudge):
    """Judge whether the final message hands over ``expected.records`` the way ``question`` asks.

    The reference list lets the judge check every record, while the exact long values stay
    with ``FinalMessageMentions``, which cannot miss a changed character.
    """

    def _prompt_template(self, question: str) -> str:
        return (
            f"{question}\n\n<records>{{{{expected.records}}}}</records>\n\n"
            "<message>{{output.last_message}}</message>\n\nAnswer `yes` or `no`."
        )

    def _prepare(self, output: dict | None, expected: dict | None) -> dict[str, Any] | Score:
        prepared = super()._prepare(output, expected)
        if isinstance(prepared, Score):
            return prepared
        return {**prepared, "expected": {"records": (_spec(expected, self._name()) or {})["records"]}}
