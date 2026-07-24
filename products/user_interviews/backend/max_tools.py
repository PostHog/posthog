from textwrap import dedent
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field
from rest_framework.serializers import ValidationError as DRFValidationError

from posthog.exceptions_capture import capture_exception
from posthog.rbac.user_access_control import AccessControlLevel
from posthog.scopes import APIScopeObject

from ee.hogai.tool import MaxTool

from .invite_email import validate_invite_message, validate_invite_subject
from .models import EmailWithDisplayNameValidator, UserInterview, UserInterviewTopic


def _topic_url(topic_id: str) -> str:
    return f"/user_research/{topic_id}"


class AnalyzeUserInterviewsArgs(BaseModel):
    analysis_angle: str = Field(
        description="How to analyze the interviews based on user's question (e.g. 'Find common pain points', 'Identify feature requests', etc.)"
    )


class AnalyzeUserInterviewsTool(MaxTool):
    name: str = "analyze_user_interviews"
    description: str = "Analyze all user interviews from a specific angle to find patterns and insights"
    context_prompt_template: str = "Since the user is currently on the user interviews page, you should lean towards the `analyze_user_interviews` when it comes to any questions about users or customers."
    args_schema: type[BaseModel] = AnalyzeUserInterviewsArgs

    def get_required_resource_access(self) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        return [("user_interview", "viewer")]

    def _run_impl(self, analysis_angle: str) -> tuple[str, Any]:
        # Get all interviews for the current team
        interviews = UserInterview.objects.filter(team=self._team).order_by("-created_at")

        if not interviews:
            return "No user interviews found to analyze.", None

        # Prepare interview summaries for analysis
        interview_summaries = []
        for interview in interviews:
            if interview.summary:
                interview_summaries.append(f"Interview from {interview.created_at}:\n{interview.summary}\n")

        if not interview_summaries:
            return "No interview summaries found to analyze.", None

        interview_summaries_text = "\n\n".join(interview_summaries)

        # Use GPT to analyze the summaries
        analysis_response = OpenAI(base_url=settings.OPENAI_BASE_URL).responses.create(
            model="gpt-4.1-mini",
            input=[
                {
                    "role": "system",
                    "content": """
You are an expert product manager analyzing user interviews. Your task is to analyze multiple interview summaries and provide insights based on the requested analysis angle.
Focus on finding patterns, common themes, and actionable insights.
""".strip(),
                },
                {
                    "role": "user",
                    "content": f"""
Please analyze these user interview summaries from the following angle:
{analysis_angle}

<interview_summaries>
{interview_summaries_text}
</interview_summaries>

Provide a structured analysis with clear sections and bullet points where appropriate. Keep it very concise though. Avoid fluff, just give the facts to answer the question.
""".strip(),
                },
            ],
        )

        return analysis_response.output_text, None


CREATE_USER_INTERVIEW_TOPIC_DESCRIPTION = dedent("""
    Create a user research interview topic — a planned voice-AI interview campaign.

    # When to use
    - The user wants to set up or run user interviews, user research, customer research,
      or "talk to users" about a feature, product area, or hypothesis.
    - The user asks to plan, schedule, draft, or kick off user interviews.

    # What this creates
    A `UserInterviewTopic` containing who to talk to (`interviewee_emails` and/or
    `interviewee_distinct_ids`), the research topic, optional context for the AI voice
    agent, and the ordered list of questions it should work through. After creation, the
    user can generate per-interviewee public links from the topic page and email invites
    to participants. The voice agent handles the live call.

    # Required information
    - `topic`: short statement of what to learn (e.g. "the new dashboard onboarding flow").
    - At least one of `interviewee_emails` OR `interviewee_distinct_ids` must be non-empty.
      Emails are preferred when known — invites can be sent automatically. PostHog distinct
      IDs work too but cannot receive email invites until an email is added.
    - `questions`: 3-6 focused, open-ended questions in the order the agent should ask
      them. Keep them conversational and avoid leading or yes/no phrasings.

    # Optional
    - `agent_context`: extra background for the voice agent — tone, what the product
      does, what NOT to ask about, who the interviewer "is" representing. Becomes part
      of the agent's system prompt for every call on this topic.

    # Important
    - This is NOT a survey. Do NOT use `create_survey` when the user asks for an
      interview, research call, or "talk to users" — those are live AI voice
      conversations, not in-app survey widgets.
    - This is NOT a session recording filter. Do NOT redirect to session recordings
      or replays when the user wants to interview people.
    - Do not invent emails or distinct IDs. If the user has not provided participants
      and you cannot derive them from the available cohort/persons tools, ask the user.
    """).strip()


class CreateUserInterviewTopicArgs(BaseModel):
    model_config = ConfigDict(extra="ignore")

    topic: str = Field(
        description=(
            "Short statement of what you want to learn from the interviews — the product "
            "area, feature, or hypothesis being researched."
        ),
    )
    interviewee_emails: list[str] = Field(
        default_factory=list,
        description=(
            "Email addresses of people to interview. Accepts plain `email@host` or the "
            "`Display Name <email@host>` form. May be combined with `interviewee_distinct_ids` "
            "but at least one of the two lists must be non-empty."
        ),
    )
    interviewee_distinct_ids: list[str] = Field(
        default_factory=list,
        description=(
            "PostHog distinct IDs of people to interview. May be combined with "
            "`interviewee_emails`, but at least one of the two lists must be non-empty. "
            "Distinct-ID-only interviewees cannot receive email invites until they are "
            "given an email address."
        ),
    )
    questions: list[str] = Field(
        default_factory=list,
        description=(
            "Ordered list of questions the AI voice agent should work through during the "
            "interview. Keep questions open-ended, conversational, and focused on the topic."
        ),
    )
    agent_context: str = Field(
        default="",
        description=(
            "Optional extra context for the voice agent — background on the product, "
            "tone, or constraints. Becomes part of the agent's system prompt for every "
            "call on this topic. Leave empty if no extra context is needed."
        ),
    )
    invite_subject: str = Field(
        default="",
        description=(
            "Optional subject line for the invitation email. Plain text only — must not contain URLs, "
            "angle brackets, or line breaks. The email template handles personalization, so do not add "
            "placeholders. Leave empty to use the default subject."
        ),
    )
    invite_message: str = Field(
        default="",
        description=(
            "Optional intro message shown in the invitation email body, above the interview link. Plain "
            "prose only (line breaks allowed) — must not contain URLs or angle brackets. Leave empty to "
            "use the default copy."
        ),
    )


class CreateUserInterviewTopicTool(MaxTool):
    name: str = "create_user_interview_topic"
    description: str = CREATE_USER_INTERVIEW_TOPIC_DESCRIPTION
    context_prompt_template: str = (
        "When the user explicitly wants to interview users, talk to users live, or run "
        "user research calls, prefer `create_user_interview_topic`. For passive, in-app "
        "feedback (e.g. NPS, opinion polls, ratings), `create_survey` is still the right "
        "choice."
    )
    args_schema: type[BaseModel] = CreateUserInterviewTopicArgs

    def get_required_resource_access(self) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        return [("user_interview", "editor")]

    async def _arun_impl(
        self,
        topic: str = "",
        interviewee_emails: list[str] | None = None,
        interviewee_distinct_ids: list[str] | None = None,
        questions: list[str] | None = None,
        agent_context: str = "",
        invite_subject: str = "",
        invite_message: str = "",
    ) -> tuple[str, dict[str, Any]]:
        emails = [e.strip() for e in (interviewee_emails or []) if e and e.strip()]
        distinct_ids = [d.strip() for d in (interviewee_distinct_ids or []) if d and d.strip()]
        questions = [q.strip() for q in (questions or []) if q and q.strip()]
        topic = (topic or "").strip()

        if not topic:
            return "Topic is required.", {
                "error": "validation_failed",
                "error_message": "Topic must be a non-empty string describing what you want to learn.",
            }

        if not emails and not distinct_ids:
            return (
                "At least one interviewee email or PostHog distinct ID must be provided.",
                {
                    "error": "validation_failed",
                    "error_message": (
                        "Provide at least one entry in `interviewee_emails` or "
                        "`interviewee_distinct_ids` so we know who to interview."
                    ),
                },
            )

        if not questions:
            return (
                "At least one interview question is required.",
                {
                    "error": "validation_failed",
                    "error_message": (
                        "Provide at least one question in `questions`. "
                        "The AI voice agent needs questions to ask during the interview."
                    ),
                },
            )

        validator = EmailWithDisplayNameValidator()
        invalid_emails: list[str] = []
        for email in emails:
            try:
                validator(email)
            except DjangoValidationError:
                invalid_emails.append(email)
        if invalid_emails:
            return (
                f"Invalid email address(es): {', '.join(invalid_emails)}",
                {
                    "error": "validation_failed",
                    "error_message": (
                        "These values are not valid email addresses: "
                        + ", ".join(invalid_emails)
                        + ". Use plain `email@host` or `Display Name <email@host>`."
                    ),
                },
            )

        try:
            invite_subject = validate_invite_subject(invite_subject or "") or ""
            invite_message = validate_invite_message(invite_message or "") or ""
        except DRFValidationError as e:
            return (
                "The invite subject or message contains disallowed content.",
                {
                    "error": "validation_failed",
                    "error_message": (
                        "The invite subject or message was rejected (URLs, angle brackets, and control "
                        f"characters are not allowed): {e.detail}"
                    ),
                },
            )

        try:
            created_topic = await UserInterviewTopic.objects.acreate(
                team=self._team,
                created_by=self._user,
                topic=topic,
                interviewee_emails=emails,
                interviewee_distinct_ids=distinct_ids,
                questions=questions,
                agent_context=agent_context or "",
                invite_subject=invite_subject,
                invite_message=invite_message,
            )
        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})
            return f"Failed to create interview topic: {str(e)}", {
                "error": "creation_failed",
                "error_message": str(e),
            }

        topic_id = str(created_topic.id)
        topic_url = _topic_url(topic_id)
        targeting_summary_parts = []
        if emails:
            targeting_summary_parts.append(f"{len(emails)} email{'s' if len(emails) != 1 else ''}")
        if distinct_ids:
            targeting_summary_parts.append(f"{len(distinct_ids)} distinct ID{'s' if len(distinct_ids) != 1 else ''}")
        targeting_summary = " + ".join(targeting_summary_parts) or "no interviewees"

        message = (
            f"Created interview topic '{topic}' targeting {targeting_summary} with "
            f"{len(questions)} question{'s' if len(questions) != 1 else ''}. "
            f"[Open topic]({topic_url}) to generate links or send invites."
        )
        return message, {
            "topic_id": topic_id,
            "topic": created_topic.topic,
            "interviewee_email_count": len(emails),
            "interviewee_distinct_id_count": len(distinct_ids),
            "question_count": len(questions),
        }
