import { type ReactElement, useState } from 'react'
import { View } from 'react-native'

import { useAuthStore } from '@/auth/authStore'
import { useDataMode } from '@/demo/demoMode'
import { useToasts, ViewsToast } from '@/features/views/ViewsToast'
import { track } from '@/lib/analytics'
import { ThumbsDownIcon } from '@/ui/icons/ThumbsDownIcon'
import { ThumbsUpIcon } from '@/ui/icons/ThumbsUpIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, radii } from '@/ui/tokens'

import { ChatFeedbackSheet } from './ChatFeedbackSheet'
import { type ChatFeedbackTarget, chatFeedbackKey } from './chatFeedback'
import { type ChatRating, useChatFeedbackStore } from './chatFeedbackStore'

interface MessageFeedbackActionsProps {
    target: ChatFeedbackTarget
}

export function MessageFeedbackActions({ target }: MessageFeedbackActionsProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const scope = useAuthStore((state) => `${state.host}|${state.user?.uuid}|${state.projectId}`)
    const mode = useDataMode()
    const key = chatFeedbackKey(`${mode}|${scope}`, target)
    const response = useChatFeedbackStore((state) => state.responses[key])
    const hydrated = useChatFeedbackStore((state) => state.hydrated)
    const [showInput, setShowInput] = useState(false)
    const toasts = useToasts()
    const properties = {
        client_surface: 'mobile',
        $ai_session_id: target.sessionId,
        $ai_trace_id: target.traceId ?? null,
        ai_product: 'posthog_ai',
        agent_runtime: target.runtime,
        task_id: target.runtime === 'sandbox' ? target.sessionId : null,
        run_id: target.runId ?? null,
        turn_index: target.turnIndex ?? null,
    }

    const rate = (rating: ChatRating): void => {
        if (useChatFeedbackStore.getState().rate(key, rating)) {
            if (mode === 'live') {
                track('$ai_metric', { ...properties, $ai_metric_name: 'quality', $ai_metric_value: rating })
            }
            if (rating === 'good') toasts.show('Thanks for your feedback')
        }
        const saved = useChatFeedbackStore.getState().responses[key]
        if (rating === 'bad' && saved?.rating === 'bad' && !saved.feedbackSent) setShowInput(true)
    }

    const sendFeedback = (text: string): void => {
        if (!text.trim() || !useChatFeedbackStore.getState().markFeedbackSent(key)) return
        if (mode === 'live') track('$ai_feedback', { ...properties, $ai_feedback_text: text.trim() })
        setShowInput(false)
        toasts.show('Thanks for your feedback')
    }

    return (
        <>
            <View style={styles.actions}>
                {response?.rating !== 'bad' ? (
                    <Pressable44
                        onPress={() => rate('good')}
                        disabled={!hydrated || response?.rating === 'good'}
                        accessibilityLabel="Good answer"
                        accessibilityState={{
                            selected: response?.rating === 'good',
                            disabled: !hydrated || !!response,
                        }}
                        style={[styles.button, response?.rating === 'good' && styles.selected]}
                        pressedBackground={colors.pressed}
                        haptic="selection"
                        testID="chat-rating-good"
                    >
                        <ThumbsUpIcon size={iconSizes.inline} color={response ? colors.ink : colors.secondary} />
                    </Pressable44>
                ) : null}
                {response?.rating !== 'good' ? (
                    <Pressable44
                        onPress={() => rate('bad')}
                        disabled={!hydrated || response?.feedbackSent}
                        accessibilityLabel="Bad answer"
                        accessibilityHint={response?.feedbackSent ? undefined : 'Opens an optional feedback form'}
                        accessibilityState={{
                            selected: response?.rating === 'bad',
                            disabled: !hydrated || !!response?.feedbackSent,
                        }}
                        style={[styles.button, response?.rating === 'bad' && styles.selected]}
                        pressedBackground={colors.pressed}
                        haptic="selection"
                        testID="chat-rating-bad"
                    >
                        <ThumbsDownIcon size={iconSizes.inline} color={response ? colors.ink : colors.secondary} />
                    </Pressable44>
                ) : null}
            </View>
            {showInput ? <ChatFeedbackSheet onClose={() => setShowInput(false)} onSubmit={sendFeedback} /> : null}
            <ViewsToast toast={toasts.toast} onHide={toasts.hide} bottom={180} />
        </>
    )
}

const useStyles = createStyles(({ colors }) => ({
    actions: { flexDirection: 'row', gap: 12 },
    button: { width: 32, height: 32, alignItems: 'center', justifyContent: 'center', borderRadius: radii.markSmall },
    selected: { backgroundColor: colors.sunken },
}))
