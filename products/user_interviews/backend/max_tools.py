from openai import OpenAI
from pydantic import BaseModel, Field

from posthog.schema import AssistantTool

from ee.hogai.tool import MaxTool
from ee.hogai.utils.types.base import ToolResult

from .models import UserInterview


class AnalyzeUserInterviewsArgs(BaseModel):
    analysis_angle: str = Field(
        description="How to analyze the interviews based on user's question (e.g. 'Find common pain points', 'Identify feature requests', etc.)"
    )


class AnalyzeUserInterviewsTool(MaxTool):
    name: str = AssistantTool.ANALYZE_USER_INTERVIEWS.value
    description: str = "Analyze all user interviews from a specific angle to find patterns and insights"
    system_prompt_template: str = "Since the user is currently on the user interviews page, you should lean towards the `analyze_user_interviews` when it comes to any questions about users or customers."
    args_schema: type[BaseModel] = AnalyzeUserInterviewsArgs

    async def _arun_impl(self, analysis_angle: str) -> ToolResult:
        # Get all interviews for the current team
        interviews = UserInterview.objects.filter(team=self._team).order_by("-created_at")

        if not interviews:
            return await self._failed_execution("No user interviews found to analyze.")

        # Prepare interview summaries for analysis
        interview_summaries = []
        for interview in interviews:
            if interview.summary:
                interview_summaries.append(f"Interview from {interview.created_at}:\n{interview.summary}\n")

        if not interview_summaries:
            return await self._failed_execution("No interview summaries found to analyze.")

        interview_summaries = "\n\n".join(interview_summaries)

        # Use GPT to analyze the summaries
        analysis_response = OpenAI().responses.create(
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
{interview_summaries}
</interview_summaries>

Provide a structured analysis with clear sections and bullet points where appropriate. Keep it very concise though. Avoid fluff, just give the facts to answer the question.
""".strip(),
                },
            ],
        )

        return await self._successful_execution(analysis_response.output_text)
