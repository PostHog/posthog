import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { getFeatureFlagPayload } from 'lib/logic/featureFlagLogic'

import type { ThreadItem } from '../types/streamTypes'
import { FeedbackRating, FeedbackTriggerType, captureFeedback } from '../utils/feedback'
import type { feedbackPromptLogicType } from './feedbackPromptLogicType'
import { runStreamLogic } from './runStreamLogic'

export interface FeedbackConfig {
    cooldownMs: number
    messageInterval: number
    samplingRate: number
    retryThreshold: number
    cancelThreshold: number
}

const STORAGE_KEY = 'posthog_ai_run_feedback_last_shown'

export interface FeedbackPromptLogicProps {
    /** Stream/logic key of the run this prompt belongs to (matches the bound `runStreamLogic`). */
    streamKey: string
    /** Telemetry session id — the conversation id when there is one, else the run id. */
    sessionId: string
}

/**
 * Decides when to show the conversation-level good/okay/bad feedback prompt for a run, tracks its
 * multi-state UI (prompt → detailed feedback → thank-you), enforces a cooldown, and emits capture events.
 *
 * Runtime-agnostic: it connects to the in-product `runStreamLogic` (never Max), triggering off the run's
 * own `markTurnComplete` / `pushHumanMessage` actions rather than a bridging hook.
 */
export const feedbackPromptLogic = kea<feedbackPromptLogicType>([
    path(['products', 'posthog_ai', 'frontend', 'logics', 'feedbackPromptLogic']),

    props({} as FeedbackPromptLogicProps),

    key((props) => props.streamKey),

    connect((props: FeedbackPromptLogicProps) => ({
        values: [runStreamLogic({ streamKey: props.streamKey }), ['traceId', 'threadItems']],
        actions: [runStreamLogic({ streamKey: props.streamKey }), ['markTurnComplete', 'pushHumanMessage']],
    })),

    actions({
        submitRating: (rating: FeedbackRating) => ({ rating }),
        completeDetailedFeedback: true,
        checkShouldShowPrompt: (messageCount: number) => ({ messageCount }),
        showPrompt: (triggerType: FeedbackTriggerType) => ({ triggerType }),
        hidePrompt: true,
        showDetailedFeedback: true,
        hideDetailedFeedback: true,
        showThankYou: true,
        hideThankYou: true,
        implicitDismissPrompt: true,
        implicitDismissDetailedFeedback: true,
        recordFeedbackShown: true,
        setLastTriggeredIntervalIndex: (index: number) => ({ index }),
    }),

    reducers({
        isPromptVisible: [
            false,
            {
                showPrompt: () => true,
                hidePrompt: () => false,
                implicitDismissPrompt: () => false,
                showDetailedFeedback: () => false,
                showThankYou: () => false,
            },
        ],
        isDetailedFeedbackVisible: [
            false,
            {
                showDetailedFeedback: () => true,
                hideDetailedFeedback: () => false,
                implicitDismissDetailedFeedback: () => false,
                hidePrompt: () => false,
            },
        ],
        isThankYouVisible: [
            false,
            {
                showThankYou: () => true,
                hideThankYou: () => false,
                showPrompt: () => false,
            },
        ],
        currentTriggerType: [
            'manual' as FeedbackTriggerType,
            {
                showPrompt: (_, { triggerType }) => triggerType,
                hidePrompt: () => 'manual' as FeedbackTriggerType,
            },
        ],
        lastTriggeredIntervalIndex: [
            0,
            {
                setLastTriggeredIntervalIndex: (_, { index }) => index,
            },
        ],
    }),

    selectors({
        feedbackConfig: [
            () => [],
            (): FeedbackConfig | null => {
                const payload = getFeatureFlagPayload(FEATURE_FLAGS.POSTHOG_AI_CONVERSATION_FEEDBACK_CONFIG)
                if (!payload || typeof payload !== 'object') {
                    posthog.captureException(
                        new Error('POSTHOG_AI_CONVERSATION_FEEDBACK_CONFIG feature flag is not set'),
                        { tags: { product: 'posthog_ai' } }
                    )
                    return null
                }
                return {
                    cooldownMs: payload.cooldownMs,
                    messageInterval: payload.messageInterval,
                    samplingRate: payload.samplingRate,
                    retryThreshold: payload.retryThreshold,
                    cancelThreshold: payload.cancelThreshold,
                }
            },
        ],
        canShowPrompt: [
            (s) => [s.feedbackConfig],
            (feedbackConfig): boolean => {
                if (!feedbackConfig) {
                    return false
                }
                const lastShown = localStorage.getItem(STORAGE_KEY)
                if (!lastShown) {
                    return true
                }
                return Date.now() - parseInt(lastShown, 10) > feedbackConfig.cooldownMs
            },
        ],
        messageInterval: [(s) => [s.feedbackConfig], (feedbackConfig): number => feedbackConfig?.messageInterval ?? 10],
        humanMessageCount: [
            (s) => [s.threadItems],
            (threadItems: ThreadItem[]): number => threadItems.filter((item) => item.type === 'human_message').length,
        ],
    }),

    listeners(({ actions, values, props, cache }) => ({
        submitRating: ({ rating }) => {
            const { sessionId } = props
            const { currentTriggerType, messageInterval, traceId, humanMessageCount } = values

            // For "bad" rating, show the detailed feedback form instead of capturing immediately
            if (rating === 'bad') {
                actions.showDetailedFeedback()
                return
            }

            captureFeedback(sessionId, traceId, rating, currentTriggerType)
            actions.recordFeedbackShown()

            // Set the interval index to current level so we don't re-trigger at the same message count
            const currentIntervalIndex = Math.floor(humanMessageCount / messageInterval)
            actions.setLastTriggeredIntervalIndex(currentIntervalIndex)

            // Show thank you for okay/good, just hide for dismissed
            if (rating === 'dismissed') {
                actions.hidePrompt()
            } else {
                actions.showThankYou()
            }
        },

        showThankYou: () => {
            cache.disposables.add(() => {
                const timer = setTimeout(() => actions.hideThankYou(), 2000)
                return () => clearTimeout(timer)
            }, 'thankYouTimer')
        },

        checkShouldShowPrompt: ({ messageCount }) => {
            const { feedbackConfig } = values
            if (!feedbackConfig) {
                return
            }

            if (values.isPromptVisible) {
                return
            }

            // Check cooldown directly (selector isn't reactive)
            const lastShown = localStorage.getItem(STORAGE_KEY)
            if (lastShown && Date.now() - parseInt(lastShown, 10) < feedbackConfig.cooldownMs) {
                return
            }

            // Message interval - only trigger once per interval
            if (messageCount > 0 && messageCount % feedbackConfig.messageInterval === 0) {
                const currentIntervalIndex = Math.floor(messageCount / feedbackConfig.messageInterval)
                if (currentIntervalIndex > values.lastTriggeredIntervalIndex) {
                    actions.setLastTriggeredIntervalIndex(currentIntervalIndex)
                    actions.showPrompt('message_interval')
                    return
                }
            }

            // Random sampling
            if (Math.random() < feedbackConfig.samplingRate) {
                actions.showPrompt('random_sample')
            }
        },

        recordFeedbackShown: () => {
            localStorage.setItem(STORAGE_KEY, Date.now().toString())
        },

        implicitDismissPrompt: () => {
            const { sessionId } = props
            const { currentTriggerType, traceId } = values

            captureFeedback(sessionId, traceId, 'implicit_dismiss', currentTriggerType)
            actions.recordFeedbackShown()
        },

        implicitDismissDetailedFeedback: () => {
            const { sessionId } = props
            const { currentTriggerType, traceId } = values

            captureFeedback(sessionId, traceId, 'bad', currentTriggerType)
            actions.recordFeedbackShown()
        },

        completeDetailedFeedback: () => {
            const { messageInterval, humanMessageCount } = values

            const currentIntervalIndex = Math.floor(humanMessageCount / messageInterval)
            actions.setLastTriggeredIntervalIndex(currentIntervalIndex)
            actions.hideDetailedFeedback()
        },

        // Run turn finished streaming — decide whether to surface the prompt.
        markTurnComplete: () => {
            if (values.humanMessageCount > 0) {
                actions.checkShouldShowPrompt(values.humanMessageCount)
            }
        },

        // User sent a follow-up while a prompt/form was open — treat it as an implicit dismissal.
        pushHumanMessage: () => {
            if (values.isPromptVisible) {
                actions.implicitDismissPrompt()
            } else if (values.isDetailedFeedbackVisible) {
                actions.implicitDismissDetailedFeedback()
            }
        },
    })),
])
