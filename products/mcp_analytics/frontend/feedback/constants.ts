export const MCP_ANALYTICS_USEFULNESS_SURVEY_ID = '01a091d3-2706-0000-124f-3aab2a5e9e11'

export const MCP_ANALYTICS_FEEDBACK_RATINGS = { UP: '1', DOWN: '2' } as const

export interface MCPAnalyticsFeedbackPromptConfig {
    entryPoint: string
    tab: string
    version: number
    question: string
    followUpQuestion: string
}

export const MCP_ANALYTICS_SESSION_FEEDBACK_PROMPT: MCPAnalyticsFeedbackPromptConfig = {
    entryPoint: 'session_review_prompt',
    tab: 'sessions',
    version: 1,
    question: 'Did this session help you find what you needed?',
    followUpQuestion: 'What did you learn, or what was missing?',
}
