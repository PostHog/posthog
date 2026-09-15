export const MCP_ANALYTICS_USEFULNESS_SURVEY_ID = '01a091d3-2706-0000-124f-3aab2a5e9e11'

export interface MCPAnalyticsFeedbackPromptConfig {
    entryPoint: string
    surveyId?: string
    tab: string
    version: number
    question?: string
    followUpQuestion?: string
}

export const MCP_ANALYTICS_SESSION_FEEDBACK_PROMPT: MCPAnalyticsFeedbackPromptConfig = {
    entryPoint: 'session_review_prompt',
    tab: 'sessions',
    version: 2,
}

export interface MCPFeedbackContext {
    visibleToolCalls: number
    visibleErrors: number
}
