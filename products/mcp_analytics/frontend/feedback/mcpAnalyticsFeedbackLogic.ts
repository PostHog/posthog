import {
    LogicWrapper,
    MakeLogicType,
    actions,
    afterMount,
    getContext,
    kea,
    key,
    listeners,
    path,
    props,
    reducers,
} from 'kea'
import posthog from 'posthog-js'

import { MCP_ANALYTICS_FEEDBACK_PROPERTIES, MCP_ANALYTICS_FEEDBACK_SURVEY_ID } from './constants'

export const FEEDBACK_PROMPT_DELAY_MS = 30_000
export const FEEDBACK_PROMPT_COOLDOWN_MS = 30 * 24 * 60 * 60 * 1000

export interface MCPAnalyticsFeedbackLogicProps {
    userId: string
    sessionId: string
    isImpersonated: boolean
}

export interface mcpAnalyticsFeedbackLogicValues {
    visible: boolean
    lastPromptAt: number
}

export interface mcpAnalyticsFeedbackLogicActions {
    schedulePrompt: () => { value: true }
    showPrompt: (timestamp: number) => { timestamp: number }
    dismissPrompt: () => { value: true }
    openSurvey: () => { value: true }
}

export type mcpAnalyticsFeedbackLogicType = MakeLogicType<
    mcpAnalyticsFeedbackLogicValues,
    mcpAnalyticsFeedbackLogicActions,
    MCPAnalyticsFeedbackLogicProps
>

export const mcpAnalyticsFeedbackLogic: LogicWrapper<mcpAnalyticsFeedbackLogicType> =
    kea<mcpAnalyticsFeedbackLogicType>([
        props({} as MCPAnalyticsFeedbackLogicProps),
        key(({ userId, sessionId }) => `${userId}:${sessionId}`),
        path((key) => ['products', 'mcp_analytics', 'frontend', 'feedback', 'mcpAnalyticsFeedbackLogic', key]),
        actions({
            schedulePrompt: true,
            showPrompt: (timestamp: number) => ({ timestamp }),
            dismissPrompt: true,
            openSurvey: true,
        }),
        reducers(({ props }) => ({
            visible: [false, { showPrompt: () => true, dismissPrompt: () => false, openSurvey: () => false }],
            lastPromptAt: [
                0,
                { persist: true, storageKey: `mcp-analytics-feedback-last-prompt:${props.userId}` },
                { showPrompt: (_, { timestamp }) => timestamp },
            ],
        })),
        listeners(({ actions, values, props, cache }) => ({
            schedulePrompt: () => {
                if (
                    !props.userId ||
                    props.isImpersonated ||
                    Date.now() - values.lastPromptAt < FEEDBACK_PROMPT_COOLDOWN_MS
                ) {
                    return
                }
                const context = getContext()
                cache.disposables.add(() => {
                    const timer = window.setTimeout(() => {
                        if (getContext() !== context) {
                            return
                        }
                        actions.showPrompt(Date.now())
                        cache.disposables.dispose('prompt-delay')
                    }, FEEDBACK_PROMPT_DELAY_MS)
                    return () => window.clearTimeout(timer)
                }, 'prompt-delay')
            },
            showPrompt: () => {
                posthog.capture('mcp analytics feedback prompt shown', MCP_ANALYTICS_FEEDBACK_PROPERTIES)
            },
            dismissPrompt: () => {
                posthog.capture('mcp analytics feedback prompt dismissed', MCP_ANALYTICS_FEEDBACK_PROPERTIES)
            },
            openSurvey: () => {
                posthog.capture('mcp analytics feedback prompt clicked', MCP_ANALYTICS_FEEDBACK_PROPERTIES)
            },
        })),
        afterMount(({ actions, cache }) => {
            cache.disposables.add(() =>
                posthog.onSurveysLoaded((surveys, context) => {
                    if (
                        context?.isLoaded &&
                        surveys.some(
                            (survey) =>
                                survey.id === MCP_ANALYTICS_FEEDBACK_SURVEY_ID && survey.start_date && !survey.end_date
                        )
                    ) {
                        actions.schedulePrompt()
                    }
                })
            )
        }),
    ])
