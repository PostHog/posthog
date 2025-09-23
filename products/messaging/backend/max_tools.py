import re
import json
from typing import Any, Optional
import uuid

from langchain_community.document_loaders import WebBaseLoader
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from ee.hogai.graph.schema_generator.parsers import PydanticOutputParserException
from ee.hogai.tool import MaxTool

from .prompts import (
    PRODUCT_DESCRIPTION_PROMPT,
    CAMPAIGN_EXAMPLES_PROMPT,
    CAMPAIGN_CREATION_PROMPT,
)


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
    thinking_message: str = "Creating your template"
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
        return ChatOpenAI(model="gpt-4.1", temperature=0.3, disable_streaming=True)

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


class CreateCampaignArgs(BaseModel):
    requirements: str = Field(
        description="The requirements for the campaign to create. Include details about triggers, actions, timing, and conditions."
    )


class CampaignOutput(BaseModel):
    name: str
    status: str = "draft"
    trigger: dict[str, Any]
    actions: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    exit_condition: str = "exit_only_at_end"
    conversion: Optional[dict[str, Any]] = None


class CreateCampaignTool(MaxTool):
    name: str = "create_campaign"
    description: str = """
    Create a marketing campaign (HogFlow) from natural language requirements.
    ALWAYS use this tool when the user:
    - Wants to create any workflow or campaign
    - Describes a sequence of actions with triggers, delays, webhooks, emails, SMS, or events
    - Asks you to build, create, or generate a workflow/campaign configuration
    - Provides requirements for a marketing automation flow
    
    DO NOT just describe how to create it - actually generate the configuration using this tool.
    """
    thinking_message: str = "Creating your campaign"
    args_schema: type[BaseModel] = CreateCampaignArgs
    show_tool_call_message: bool = False

    def _run_impl(self, requirements: str) -> tuple[str, str]:
        system_content = f"""
{PRODUCT_DESCRIPTION_PROMPT}

{CAMPAIGN_EXAMPLES_PROMPT}

You are creating a HogFlow campaign configuration.
Generate a valid JSON object that follows the HogFlow schema.
Each action needs these fields: id, name, type, description, and config (when applicable).
Ensure all IDs are unique strings.
Return ONLY the JSON object without any markdown formatting or explanation.
"""
        
        user_content = CAMPAIGN_CREATION_PROMPT.format(requirements=requirements)
        
        messages: list[SystemMessage | HumanMessage] = [
            SystemMessage(content=system_content),
            HumanMessage(content=user_content)
        ]

        final_error: Optional[Exception] = None
        parsed_result = None
        
        for _ in range(3):
            try:
                result = self._model.invoke(messages)
                parsed_result = self._parse_campaign_output(result.content)
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
                llm_output=result.content, validation_message="The model did not return a valid campaign configuration."
            )

        # Ensure all actions have required fields
        import time
        current_timestamp = int(time.time() * 1000)
        for action in parsed_result.actions:
            if "created_at" not in action:
                action["created_at"] = current_timestamp
            if "updated_at" not in action:
                action["updated_at"] = current_timestamp
            if "on_error" not in action:
                action["on_error"] = "continue"

        campaign_json = json.dumps(parsed_result.model_dump(), indent=2)
        return f"```json\n{campaign_json}\n```", campaign_json

    @property
    def _model(self):
        return ChatOpenAI(model="gpt-4o", temperature=0.3, disable_streaming=True)

    def _parse_campaign_output(self, output: str) -> CampaignOutput:
        # Remove markdown formatting if present
        json_str = re.sub(
            r"^\s*```(?:json)?\s*\n(.*?)\n\s*```\s*$", r"\1", output, flags=re.DOTALL | re.MULTILINE
        ).strip()
        
        if not json_str:
            json_str = output.strip()

        try:
            campaign_data = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise PydanticOutputParserException(
                llm_output=json_str, validation_message=f"The campaign JSON failed to parse: {str(e)}"
            )

        return CampaignOutput(**campaign_data)
