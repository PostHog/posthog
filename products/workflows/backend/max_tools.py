import re
import json
from typing import Any, Optional

from langchain_community.document_loaders import WebBaseLoader
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, ValidationError

from posthog.security.url_validation import is_url_allowed

from ee.hogai.chat_agent.schema_generator.parsers import PydanticOutputParserException
from ee.hogai.llm import MaxChatOpenAI
from ee.hogai.tool import MaxTool

# Compact but valid Unlayer design skeleton, shown to the model so the generated `design`
# loads natively in the visual editor (body → rows → columns → contents, each with a unique id).
UNLAYER_DESIGN_EXAMPLE = """{"counters":{"u_row":1,"u_column":1,"u_content_text":1},"body":{"id":"body1","rows":[{"id":"row1","cells":[1],"columns":[{"id":"col1","contents":[{"id":"txt1","type":"text","values":{"text":"<p>Hi {{ person.properties.name }}</p>"}}],"values":{}}],"values":{}}],"values":{},"headers":[],"footers":[]},"schemaVersion":17}"""


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
    description: str = "Create a message template from a prompt, optionally using a URL to inform the content."
    args_schema: type[BaseModel] = CreateTemplateArgs

    def _run_impl(self, instructions: str) -> tuple[str, str]:
        url_match = re.search(r"https" r"?://\S+", instructions)
        url = url_match.group(0) if url_match else None
        # This endpoint is reachable over the public API/MCP, so the URL is attacker-controlled —
        # block private/internal/link-local targets before we fetch (SSRF guard).
        if url:
            allowed, _reason = is_url_allowed(url)
            if not allowed:
                url = None

        system_content = f"""
You are an expert at writing marketing copy and designing branded email templates.
The user will provide instructions for a message template.
You should generate a JSON object with the template details.
The JSON object should have the following keys: "name", "description", and "content".
The "content" field should be a JSON object with two keys: "email" and "templating".
The "email" field should be a JSON object with "html", "text", "design", and "subject" keys.
The "design" object MUST use Unlayer's JSON format: a "body" with a "rows" array, each row having "columns",
each column having a "contents" array of blocks (type "text", "button", "image", "divider"). Every row, column,
and content block needs a unique string "id". Include "counters" and "schemaVersion". This is what makes the
template editable in the visual editor, so it must be valid Unlayer JSON. Example:
{UNLAYER_DESIGN_EXAMPLE}
The "html" field must be the rendered HTML of that same design — they describe one email, keep them consistent.
The "templating" field should be set to "liquid". Write personalization as Liquid tags,
e.g. {{{{ person.properties.email }}}} or {{{{ person.properties.name }}}}.
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

        try:
            parsed = TemplateOutput(**template)
        except ValidationError as e:
            # Surface shape/type errors (e.g. design returned as a string) as a parser
            # exception so the retry loop in _run_impl can self-correct instead of 500ing.
            raise PydanticOutputParserException(
                llm_output=json_str, validation_message=f"The template structure is invalid: {str(e)}"
            )
        self._validate_design(parsed.content.email.design)
        return parsed

    @staticmethod
    def _validate_design(design: dict[str, Any]) -> None:
        """Shape-check the Unlayer design so it loads in the visual editor.

        We can only validate structure — there's no server-side Unlayer renderer — but a missing
        body/rows or schemaVersion reliably means the editor would open blank. Failures feed the
        retry loop in _run_impl so the model gets a chance to self-correct.
        """
        body = design.get("body") if isinstance(design, dict) else None
        rows = body.get("rows") if isinstance(body, dict) else None
        if not isinstance(rows, list) or not rows:
            raise PydanticOutputParserException(
                llm_output=json.dumps(design),
                validation_message="The design must be valid Unlayer JSON with a non-empty body.rows array.",
            )
        if "schemaVersion" not in design:
            raise PydanticOutputParserException(
                llm_output=json.dumps(design),
                validation_message="The design is missing the required Unlayer 'schemaVersion' field.",
            )
