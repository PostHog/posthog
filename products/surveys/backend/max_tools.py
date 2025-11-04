"""
MaxTool for AI-powered survey creation.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

from posthog.schema import SurveyAnalysisQuestionGroup

from posthog.exceptions_capture import capture_exception

from ee.hogai.llm import MaxChatOpenAI
from ee.hogai.tool import MaxTool

from .prompts import SURVEY_ANALYSIS_SYSTEM_PROMPT


class SurveyAnalysisArgs(BaseModel):
    """
    Analyze survey responses to extract themes, sentiment, and actionable insights from open-ended questions.
    All survey data and responses are automatically provided from context.
    """


class QuestionBreakdown(BaseModel):
    """Analysis breakdown for a specific question"""

    theme: str = Field(description="Main theme for this question")
    sentiment: Literal["positive", "negative", "mixed", "neutral"] = Field(
        description="Sentiment for this question", default="neutral"
    )
    key_insights: list[str] = Field(description="Key insights for this question")


class ThemeWithExamples(BaseModel):
    """Theme with supporting response examples"""

    theme: str = Field(description="Main theme name")
    description: str = Field(description="Brief explanation of the theme")
    examples: list[str] = Field(description="1-2 actual response examples that illustrate this theme", max_length=2)


class SurveyAnalysisOutput(BaseModel):
    themes: list[ThemeWithExamples] = Field(description="Key themes with examples from actual responses")
    sentiment: Literal["positive", "negative", "mixed", "neutral"] = Field(
        description="Overall sentiment analysis", default="neutral"
    )
    insights: list[str] = Field(description="Actionable insights derived from the data")
    recommendations: list[str] = Field(description="Specific recommendations based on analysis")
    response_count: int = Field(description="Total number of open-ended responses analyzed", default=0)
    question_breakdown: dict[str, QuestionBreakdown] | None = Field(
        description="Analysis breakdown by question ID", default=None
    )


class SurveyAnalysisTool(MaxTool):
    name: str = "analyze_survey_responses"
    description: str = (
        "Analyze survey responses to extract themes, sentiment, and actionable insights from open-ended questions"
    )
    context_prompt_template: str = (
        "You have access to a survey analysis tool that can analyze open-ended responses to identify themes, sentiment, and actionable insights. "
        "When users ask about analyzing survey responses, summarizing feedback, finding patterns in responses, or extracting insights from survey data, "
        "use the analyze_survey_responses tool. Survey data includes: {formatted_responses}"
    )

    args_schema: type[BaseModel] = SurveyAnalysisArgs

    def _extract_open_ended_responses(self) -> list[SurveyAnalysisQuestionGroup]:
        """
        Extract open-ended responses from context.
        Returns a list of validated SurveyAnalysisQuestionGroup objects.
        """
        if not hasattr(self, "context") or not self.context:
            return []

        raw_responses = self.context.get("formatted_responses", [])
        if not raw_responses:
            return []

        responses = []
        for group in raw_responses:
            try:
                # Apply response limit and validate with Pydantic
                validated_group = SurveyAnalysisQuestionGroup.model_validate(
                    {
                        **group,
                        "responses": group.get("responses", [])[:50],  # Limit to 50 responses per question
                    }
                )
                responses.append(validated_group)
            except Exception:
                # Skip invalid groups
                continue

        return responses

    async def _analyze_responses(
        self, question_groups: list[SurveyAnalysisQuestionGroup], analysis_focus: str = "comprehensive"
    ) -> SurveyAnalysisOutput:
        """
        Analyze the extracted responses using LLM to generate themes, sentiment, and insights.

        Expected format:
        [
          {
            questionName: "What do you think?",
            questionId: "123",
            responses: [
              {responseText: "Great!", userDistinctId: "user1", email: "user@example.com", isOpenEnded: true},
              {responseText: "Good", userDistinctId: "user2", email: null, isOpenEnded: true}
            ]
          }
        ]
        """
        if not question_groups:
            return SurveyAnalysisOutput(
                themes=[],
                sentiment="neutral",
                insights=["No open-ended responses found to analyze."],
                recommendations=["Consider adding open-ended questions to gather more detailed feedback."],
                response_count=0,
                question_breakdown=None,
            )

        # Count total responses across all questions
        total_response_count = sum(len(group.responses or []) for group in question_groups)

        try:
            # Format the data for LLM analysis
            formatted_data = self._format_responses_for_llm(question_groups)

            # Initialize LLM with PostHog context and structured output
            llm = MaxChatOpenAI(
                user=self._user,
                team=self._team,
                model="gpt-4.1",
                temperature=0.1,  # Lower temperature for consistent analysis
            ).with_structured_output(SurveyAnalysisOutput)

            # Create the analysis prompt by directly substituting the data
            formatted_prompt = SURVEY_ANALYSIS_SYSTEM_PROMPT.replace("{{{survey_responses}}}", formatted_data)

            # Generate analysis with structured output
            analysis_result = await llm.ainvoke([{"role": "system", "content": formatted_prompt}])

            # Ensure response_count is accurate (don't rely on LLM calculation)
            if hasattr(analysis_result, "response_count"):
                analysis_result.response_count = total_response_count
            elif isinstance(analysis_result, dict):
                analysis_result["response_count"] = total_response_count

            # Ensure we return the proper type
            if isinstance(analysis_result, dict):
                return SurveyAnalysisOutput(**analysis_result)
            return analysis_result

        except Exception as e:
            # Don't mask the error - let the user know something went wrong
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})

            # Return an error message instead of a fake success
            error_message = f"❌ Survey analysis failed: {str(e)}"
            return SurveyAnalysisOutput(
                themes=[],
                sentiment="neutral",
                insights=[error_message],
                recommendations=["Try the analysis again, or contact support if the issue persists"],
                response_count=total_response_count,
                question_breakdown=None,
            )

    def _format_responses_for_llm(self, question_groups: list[SurveyAnalysisQuestionGroup]) -> str:
        """
        Format the grouped responses into a token-efficient string for LLM analysis.
        Optimized to reduce token usage by avoiding repetition and using compact formatting.
        """
        formatted_sections = []

        for group in question_groups:
            question_name = group.questionName
            responses = group.responses

            formatted_sections.append(f'Q: "{question_name}"')

            # Group responses without repeating question for each response
            response_texts = []
            if responses:  # Ensure responses is not None
                for response in responses:
                    response_text = response.responseText
                    # Include only response text for analysis
                    response_texts.append(f'"{response_text}"')

            formatted_sections.append("Responses:\n" + "\n".join(f"- {text}" for text in response_texts))
            formatted_sections.append("")  # Empty line between questions

        return "\n".join(formatted_sections)

    def _format_analysis_for_user(self, analysis: SurveyAnalysisOutput, survey_name: str) -> str:
        """Format the structured analysis into a user-friendly message."""
        lines = []

        # Header with response count
        header = f"✅ **Survey Analysis: '{survey_name}'**"
        lines.append(header)
        lines.append(f"*Analyzed {analysis.response_count} open-ended responses*")
        lines.append("\n---")

        # Overall sentiment first for context
        sentiment_emoji = {"positive": "😊", "negative": "😞", "mixed": "🤔", "neutral": "😐"}.get(
            analysis.sentiment, "😐"
        )
        lines.append(f"**📊 Overall Sentiment:** {sentiment_emoji} {analysis.sentiment.title()}")

        # Key themes with examples
        if analysis.themes:
            lines.append("\n**🎯 Key Themes:**")
            for i, theme in enumerate(analysis.themes[:5], 1):  # Limit to top 5 themes
                lines.append(f"\n**{i}. {theme.theme}**")
                lines.append(f"{theme.description}")
                if theme.examples:
                    lines.append("\n**Examples:**")
                    for example in theme.examples[:2]:  # Max 2 examples per theme
                        lines.append(f'- "{example}"')
                if i < len(analysis.themes[:5]):  # Don't add separator after last theme
                    lines.append("\n---")

        # Key insights with better formatting
        if analysis.insights:
            lines.append("\n**💡 Key Insights:**")
            for i, insight in enumerate(analysis.insights[:3], 1):  # Limit to top 3 insights
                lines.append(f"\n{i}. {insight}")

        # Recommendations with action-oriented formatting
        if analysis.recommendations:
            lines.append("\n**🚀 Recommendations:**")
            for i, rec in enumerate(analysis.recommendations[:3], 1):  # Top 3 recommendations
                lines.append(f"\n**{i}.** {rec}")

        # Question breakdown with improved structure
        if analysis.question_breakdown:
            lines.append("\n**📝 Question Breakdown:**")
            for question, breakdown in list(analysis.question_breakdown.items())[:3]:  # Top 3 questions
                lines.append(f"\n**Q: {question}**")
                lines.append(f"\nTheme: {breakdown.theme}")
                lines.append(f"\nSentiment: {breakdown.sentiment.title()}")
                if breakdown.key_insights:
                    lines.append("\nKey insights:")
                    for insight in breakdown.key_insights[:2]:  # Limit to 2 insights per question
                        lines.append(f"- {insight}")

        lines.append("\n---")
        lines.append("💡 *Need more detail? Ask me to dive deeper into any specific aspect.*")

        return "\n".join(lines)

    async def _arun_impl(self) -> tuple[str, dict[str, Any]]:
        """
        Analyze survey responses to extract actionable insights from open-ended questions.
        All survey data and responses come from the context provided by the frontend.
        """
        try:
            # Get survey info from context
            survey_id = self.context.get("survey_id")
            survey_name = self.context.get("survey_name", "Unknown Survey")
            # Get pre-formatted responses from frontend (already in correct format)
            raw_responses = self.context.get("formatted_responses", [])
            if not raw_responses:
                responses = []
            else:
                # Apply response limit and validate with Pydantic
                responses = [
                    SurveyAnalysisQuestionGroup.model_validate(
                        {
                            **group,
                            "responses": group.get("responses", [])[:50],  # Limit to 50 responses per question
                        }
                    )
                    for group in raw_responses
                ]

            if not survey_id or not responses:
                return "❌ No survey data provided", {
                    "error": "no_survey_data",
                    "details": "Survey information not found in context",
                }

            # Analyze the responses
            analysis_result = await self._analyze_responses(responses)

            if analysis_result.response_count == 0:
                success_message = f"ℹ️ No open-ended responses found in survey '{survey_name}' to analyze"
                return success_message, {
                    "survey_id": survey_id,
                    "survey_name": survey_name,
                    "analysis": analysis_result.model_dump(),
                }

            # Format the analysis as a user-friendly message
            user_message = self._format_analysis_for_user(analysis_result, survey_name)

            return user_message, {
                "survey_id": survey_id,
                "survey_name": survey_name,
                "analysis": analysis_result.model_dump(),
            }

        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})
            return f"❌ Failed to analyze survey responses: {str(e)}", {"error": "analysis_failed", "details": str(e)}
