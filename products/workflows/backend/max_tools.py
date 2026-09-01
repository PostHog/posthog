import re
import html as html_lib
import json
from textwrap import dedent
from typing import Any, Optional

from django.test import RequestFactory

from langchain_community.document_loaders import WebBaseLoader
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from rest_framework import serializers

from posthog.dataclasses import frozen
from posthog.event_usage import EventSource
from posthog.exceptions_capture import capture_exception
from posthog.models.integration import Integration
from posthog.rbac.user_access_control import AccessControlLevel
from posthog.scopes import APIScopeObject
from posthog.sync import database_sync_to_async

from products.workflows.backend.api.hog_flow import HogFlowSerializer
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

from ee.hogai.chat_agent.schema_generator.parsers import PydanticOutputParserException
from ee.hogai.llm import MaxChatOpenAI
from ee.hogai.tool import MaxTool


class CreateTemplateArgs(BaseModel):
    instructions: str = Field(description="The instructions for what template to create. This can include a URL.")


class EmailContent(BaseModel):
    html: str
    text: str
    design: dict[str, Any]
    subject: str


class ContentModel(BaseModel):
    email: EmailContent
    templating: str


class TemplateOutput(BaseModel):
    name: str
    description: Optional[str] = ""
    content: ContentModel


class CreateMessageTemplateTool(MaxTool):
    name: str = "create_message_template"
    description: str = "Create an email/message template in the workflows messaging library from the user's instructions, optionally fetching a URL to match their branding and content."
    args_schema: type[BaseModel] = CreateTemplateArgs

    def _run_impl(self, instructions: str) -> tuple[str, str]:
        url_match = re.search(r"https" r"?://\S+", instructions)
        url = url_match.group(0) if url_match else None

        system_content = """
You are an expert at writing marketing copy and designing branded email templates.
The user will provide instructions for a message template.
You should generate a JSON object with the template details.
The JSON object should have the following keys: "name", "description", and "content".
The "content" field should be a JSON object with two keys: "email" and "templating".
The "email" field should be a JSON object with "html", "text", "design", and "subject" keys.
The "design" object should use Unlayer's JSON format to represent the email's visual structure. Make sure this is a valid Unlayer JSON structure.
The "templating" field should usually be set to "hog".
Return ONLY the JSON object. Do not add any other text or explanation.
"""
        user_content = f"Create a template for these instructions: {instructions}"
        messages: list[SystemMessage | HumanMessage] = [SystemMessage(content=system_content)]

        if url:
            try:
                loader = WebBaseLoader(url)
                docs = loader.load()
                page_content = " ".join([doc.page_content for doc in docs])
                # Truncate to avoid excessive length
                page_content = page_content[:10000]

                user_content_with_context = f"""
Here is the content from the URL {url}:
---
{page_content}
---
Now, create a template for these instructions: {instructions}
"""
                messages.append(HumanMessage(content=user_content_with_context))
            except Exception:
                # If fetching fails, just use the original instructions
                messages.append(HumanMessage(content=user_content))
        else:
            messages.append(HumanMessage(content=user_content))

        final_error: Optional[Exception] = None
        parsed_result = None
        for _ in range(3):
            try:
                result = self._model.invoke(messages)
                parsed_result = self._parse_output(result.content)
                break
            except PydanticOutputParserException as e:
                system_content += f"\n\nAvoid this error: {str(e)}"
                messages[0] = SystemMessage(content=system_content)
                final_error = e
        else:
            if final_error is not None:
                raise final_error

        if parsed_result is None:
            raise PydanticOutputParserException(
                llm_output=result.content, validation_message="The model did not return a valid template."
            )

        template_json = json.dumps(parsed_result.model_dump(), indent=2)
        return f"```json\n{template_json}\n```", template_json

    @property
    def _model(self):
        return MaxChatOpenAI(
            model="gpt-4.1",
            temperature=0.3,
            disable_streaming=True,
            user=self._user,
            team=self._team,
            billable=True,
            inject_context=False,
        )

    def _parse_output(self, output: str) -> TemplateOutput:
        match = re.search(r"<template>(.*?)</template>", output, re.DOTALL)
        if not match:
            json_str = re.sub(
                r"^\s*```json\s*\n(.*?)\n\s*```\s*$", r"\1", output, flags=re.DOTALL | re.MULTILINE
            ).strip()
        else:
            json_str = match.group(1).strip()

        if not json_str:
            raise PydanticOutputParserException(
                llm_output=output, validation_message="The model returned an empty template response."
            )

        try:
            template = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise PydanticOutputParserException(
                llm_output=json_str, validation_message=f"The template JSON failed to parse: {str(e)}"
            )

        return TemplateOutput(**template)


class BroadcastAudienceCondition(BaseModel):
    type: str = Field(
        description="Condition type: 'person' (a person property condition) or 'cohort' (a cohort reference). "
        "Event/behavioral conditions are not supported for broadcast audiences."
    )
    key: str = Field(description="Person property name for type 'person'; the literal 'id' for type 'cohort'.")
    value: Any = Field(description="Property value(s) for type 'person' (usually a list); cohort id for type 'cohort'.")
    operator: str = Field(
        default="exact", description="Filter operator, e.g. 'exact', 'icontains', 'is_set'. Use 'in' for cohorts."
    )


class BroadcastConversionGoal(BaseModel):
    event_name: str = Field(description="Event that counts as a conversion after the send.")
    window_minutes: Optional[int] = Field(
        default=10080, description="Minutes after entry within which the event counts. Defaults to 7 days."
    )


class CreateBroadcastArgs(BaseModel):
    name: str = Field(description="Broadcast name.")
    audience_conditions: list[BroadcastAudienceCondition] = Field(
        default_factory=list,
        description="Who receives the broadcast: person-property conditions and/or static or property-based "
        "cohort references. An empty list means everyone. Behavioral targeting ('did event X') is unsupported.",
    )
    email_subject: str = Field(description="Email subject line.")
    email_html: Optional[str] = Field(
        default=None, description="HTML email body. Omit to derive a simple HTML body from email_text."
    )
    email_text: Optional[str] = Field(
        default=None, description="Plain-text email body (fallback for clients that block rich content)."
    )
    from_email: Optional[str] = Field(
        default=None,
        description="Sender address. Omit to use the project's verified email sender integration.",
    )
    from_name: Optional[str] = Field(default=None, description="Sender display name.")
    conversion_goal: Optional[BroadcastConversionGoal] = Field(
        default=None, description="Optional conversion goal to track after the send."
    )
    schedule_intent: Optional[str] = Field(
        default=None,
        description="Optional free-text note on when the user wants this sent (e.g. 'next Monday 9am'). "
        "The broadcast is NEVER sent or scheduled by this tool; the note is echoed back for the review step.",
    )


_ALLOWED_AUDIENCE_CONDITION_TYPES = frozenset({"person", "cohort"})


@frozen
class _BroadcastGraph:
    actions: list[dict[str, Any]]
    edges: list[dict[str, Any]]


def _text_to_html(text: str) -> str:
    paragraphs = [f"<p>{html_lib.escape(p.strip())}</p>" for p in text.split("\n\n") if p.strip()]
    body = "\n".join(paragraphs)
    return f'{body}\n<p><a href="{{{{ unsubscribe_url }}}}">Unsubscribe</a></p>'


class CreateBroadcastTool(MaxTool):
    name: str = "create_broadcast"
    description: str = dedent("""
        Create a DRAFT broadcast: a one-time or scheduled email send to an audience of people.

        # When to use
        - The user wants to send a broadcast, blast, newsletter, or announcement email
        - The user wants to "email everyone who..." matches some person properties or a cohort

        # Audience
        Person-property conditions and static/property-based cohorts only. Behavioral targeting
        ("did event X in the last N days") is unsupported for broadcasts — tell the user instead
        of approximating it.

        # After creation
        This tool only creates a draft. It never sends, schedules, or activates anything.
        Share the returned link so the user can review the audience, email content, and
        schedule in the broadcasts UI before sending.
        """).strip()
    args_schema: type[BaseModel] = CreateBroadcastArgs

    def get_required_resource_access(self) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        return [("hog_flow", "editor")]

    def _resolve_sender(self, from_email: Optional[str], from_name: Optional[str]) -> Optional[dict[str, str]]:
        if from_email:
            return {"email": from_email, "name": from_name or ""}
        integration = (
            Integration.objects.filter(team=self._team, kind="email", config__verified=True)
            .order_by("created_at")
            .first()
        )
        if integration is None:
            return None
        return {"email": integration.config.get("email", ""), "name": from_name or integration.config.get("name", "")}

    def _build_actions(
        self,
        properties: list[dict[str, Any]],
        email_subject: str,
        email_html: str,
        email_text: str,
        sender: dict[str, str],
    ) -> _BroadcastGraph:
        actions: list[dict[str, Any]] = [
            {
                "id": "trigger_audience",
                "name": "Audience",
                "type": "trigger",
                "config": {"type": "batch", "filters": {"properties": properties}},
            },
            {
                "id": "email_broadcast",
                "name": "Broadcast email",
                "type": "function_email",
                "config": {
                    "template_id": "template-email",
                    "message_category_type": "marketing",
                    "inputs": {
                        "email": {
                            "value": {
                                "to": {"email": "{{ person.properties.email }}", "name": ""},
                                "from": sender,
                                "subject": email_subject,
                                "text": email_text,
                                "html": email_html,
                            },
                            "templating": "liquid",
                        }
                    },
                },
            },
            {"id": "exit_done", "name": "Exit", "type": "exit", "config": {"reason": "Broadcast sent"}},
        ]
        edges: list[dict[str, Any]] = [
            {"from": "trigger_audience", "to": "email_broadcast", "type": "continue"},
            {"from": "email_broadcast", "to": "exit_done", "type": "continue"},
        ]
        return _BroadcastGraph(actions=actions, edges=edges)

    def _create_broadcast(
        self,
        name: str,
        properties: list[dict[str, Any]],
        email_subject: str,
        email_html: str,
        email_text: str,
        sender: dict[str, str],
        conversion_goal: Optional[BroadcastConversionGoal],
    ) -> HogFlow:
        graph = self._build_actions(properties, email_subject, email_html, email_text, sender)
        data: dict[str, Any] = {
            "name": name,
            "kind": HogFlow.Kind.BROADCAST,
            "status": HogFlow.State.DRAFT,
            "exit_condition": HogFlow.ExitCondition.ONLY_AT_END,
            "actions": graph.actions,
            "edges": graph.edges,
        }
        if conversion_goal is not None:
            data["conversion"] = {
                "events": [
                    {
                        "filters": {
                            "events": [
                                {
                                    "id": conversion_goal.event_name,
                                    "name": conversion_goal.event_name,
                                    "type": "events",
                                }
                            ]
                        }
                    }
                ],
                "filters": [],
                "window_minutes": conversion_goal.window_minutes,
            }

        # The serializer expects a request context; mirror the internal-caller pattern from
        # posthog/management/commands/refresh_hog_flows.py. event_source makes draft validation
        # strict, so a bad audience (event filters, behavioral cohorts) fails here, not at enable.
        request = RequestFactory().post("/")
        request.user = self._user
        serializer = HogFlowSerializer(
            data=data,
            context={
                "request": request,
                "team_id": self._team.id,
                "get_team": lambda: self._team,
                "event_source": EventSource.POSTHOG_AI,
            },
        )
        serializer.is_valid(raise_exception=True)
        return serializer.save()

    async def _arun_impl(
        self,
        name: str,
        audience_conditions: list[BroadcastAudienceCondition] | None = None,
        email_subject: str = "",
        email_html: Optional[str] = None,
        email_text: Optional[str] = None,
        from_email: Optional[str] = None,
        from_name: Optional[str] = None,
        conversion_goal: Optional[BroadcastConversionGoal] = None,
        schedule_intent: Optional[str] = None,
    ) -> tuple[str, dict[str, Any]]:
        audience_conditions = audience_conditions or []

        unsupported = sorted({c.type for c in audience_conditions if c.type not in _ALLOWED_AUDIENCE_CONDITION_TYPES})
        if unsupported:
            return (
                f"Broadcast audiences can't use {', '.join(unsupported)} conditions. They target who a person is, "
                "not what they did: use person properties or a static/property-based cohort. For behavioral "
                "targeting ('did event X'), an event-triggered workflow is the right tool instead.",
                {"error": "validation_failed", "error_message": f"Unsupported audience condition types: {unsupported}"},
            )

        if not email_subject:
            return "A broadcast email needs a subject line.", {
                "error": "validation_failed",
                "error_message": "email_subject is required.",
            }
        if not email_html and not email_text:
            return "Provide the email body as email_html and/or email_text.", {
                "error": "validation_failed",
                "error_message": "One of email_html or email_text is required.",
            }

        properties: list[dict[str, Any]] = [
            {"key": c.key, "value": c.value, "operator": c.operator, "type": c.type} for c in audience_conditions
        ]
        text = email_text or ""
        html = email_html or _text_to_html(text)

        try:
            sender = await database_sync_to_async(self._resolve_sender)(from_email, from_name)
            if sender is None:
                return (
                    "No sender address available. Ask the user for the from address to send this broadcast from, "
                    "or have them connect a verified email sender in the workflows settings, then try again.",
                    {"error": "validation_failed", "error_message": "No from_email and no verified email integration."},
                )
            hog_flow = await database_sync_to_async(self._create_broadcast)(
                name, properties, email_subject, html, text, sender, conversion_goal
            )
        except serializers.ValidationError as e:
            error_message = str(e.detail if hasattr(e, "detail") else e)
            return f"Broadcast validation failed: {error_message}", {
                "error": "validation_failed",
                "error_message": error_message,
            }
        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})
            return f"Failed to create broadcast: {str(e)}", {"error": "creation_failed", "details": str(e)}

        url = f"/workflows/broadcasts/{hog_flow.id}"
        schedule_note = (
            f" You asked to send it: {schedule_intent}. Set that schedule there too." if schedule_intent else ""
        )
        message = (
            f"Draft broadcast '{hog_flow.name}' created. Nothing has been sent or scheduled. "
            f"[Review the audience, email content, and schedule]({url}) before sending.{schedule_note}"
        )
        return message, {
            "broadcast_id": str(hog_flow.id),
            "broadcast_name": hog_flow.name,
            "kind": "broadcast",
            "status": hog_flow.status,
        }
