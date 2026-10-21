import type { SurveyFeedbackPromptConfig } from 'lib/logic/surveyFeedbackPrompt/surveyFeedbackPromptLogic'

export const MCP_ANALYTICS_USEFULNESS_SURVEY_ID = '01a091d3-2706-0000-124f-3aab2a5e9e11'

// pinned: localStorage key prefix, renaming it resets every person's cooldown
export const MCP_ANALYTICS_FEEDBACK_COOLDOWN_STORAGE_KEY = 'mcp-analytics-feedback-last-prompt'

export const MCP_ANALYTICS_SESSION_FEEDBACK_PROMPT: SurveyFeedbackPromptConfig = {
    surface: 'mcp_analytics',
    entryPoint: 'session_review_prompt',
    version: 1,
    question: 'Did this session help you find what you needed?',
    followUpQuestion: 'What did you learn, or what was missing?',
    properties: { mcp_analytics_tab: 'sessions' },
}

export const MCP_ANALYTICS_DASHBOARD_FEEDBACK_PROMPT: SurveyFeedbackPromptConfig = {
    surface: 'mcp_analytics',
    entryPoint: 'dashboard_review_prompt',
    version: 1,
    question: 'Did this dashboard help you understand how your MCP server is being used?',
    followUpQuestion: 'What did you learn, or what was missing?',
    properties: { mcp_analytics_tab: 'dashboard' },
}
