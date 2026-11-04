import { randomUUID } from 'expo-crypto'
import { type ReactElement, useEffect, useMemo, useRef, useState } from 'react'
import { ActivityIndicator, Text, TextInput } from 'react-native'
import { Gesture, GestureDetector } from 'react-native-gesture-handler'
import { useKeyboardState, useReanimatedKeyboardAnimation } from 'react-native-keyboard-controller'
import Animated from 'react-native-reanimated'
import { BottomSheet } from '@/ui/BottomSheet'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useTheme } from '@/ui/theme'
import { inputReset, radii, type } from '@/ui/tokens'
import { useSceneDimensions } from '@/ui/useSceneDimensions'

import { FEEDBACK_MAX_LENGTH, feedbackDismissed, feedbackShown, sendFeedback } from './feedbackSurvey'

interface FeedbackSheetProps {
    visible: boolean
    /** Where the team replies. The sheet shows it next to the promise to follow up. */
    email?: string
    onClose: () => void
    onSent: () => void
}

export function FeedbackSheet({ visible, email, onClose, onSent }: FeedbackSheetProps): ReactElement {
    const styles = useStyles()
    const { colors, scheme } = useTheme()
    const { height } = useSceneDimensions()
    const keyboardHeight = useKeyboardState((state) => state.height)
    const compact = height - keyboardHeight < 480
    const keyboard = useReanimatedKeyboardAnimation()
    const scrollGesture = useMemo(() => Gesture.Native(), [])
    const [message, setMessage] = useState('')
    const [sending, setSending] = useState(false)
    const [error, setError] = useState(false)
    const inFlight = useRef(false)
    const submissionId = useRef<string | null>(null)
    // The sheet stays pressable while it animates out, so a second tap must not send again or count as a dismissal.
    const sent = useRef(false)

    useEffect(() => {
        if (visible) {
            sent.current = false
            feedbackShown()
        }
    }, [visible])

    const trimmed = message.trim()
    const canSend = trimmed.length > 0 && !sending

    const dismiss = (): void => {
        if (!sent.current) {
            feedbackDismissed()
        }
        onClose()
    }
    const send = async (): Promise<void> => {
        if (!canSend || sent.current || inFlight.current) {
            return
        }
        inFlight.current = true
        setSending(true)
        setError(false)
        try {
            submissionId.current ??= randomUUID()
            await sendFeedback(trimmed, email, submissionId.current)
            sent.current = true
            setMessage('')
            submissionId.current = null
            onSent()
        } catch {
            setError(true)
        } finally {
            inFlight.current = false
            setSending(false)
        }
    }

    return (
        <BottomSheet
            visible={visible}
            onClose={dismiss}
            paddingHorizontal={20}
            keyboardHeight={keyboard.height}
            scrollGesture={scrollGesture}
            accessibilityLabel="Send feedback"
            testID="feedback-sheet"
        >
            <GestureDetector gesture={scrollGesture}>
                <Animated.ScrollView style={styles.content} keyboardShouldPersistTaps="handled">
                    <Text style={styles.title} accessibilityRole="header">
                        Send feedback
                    </Text>
                    <Text style={styles.description} testID="feedback-description">
                        {compact
                            ? 'Send a message to the PostHog team.'
                            : 'Share ideas, bugs, or anything else on your mind. Your message goes straight to the PostHog team.'}
                        {email ? (
                            <>
                                {' Your email goes with the message so we can reply: '}
                                <Text style={styles.email}>{email}</Text>.
                            </>
                        ) : (
                            " Your email won't be included."
                        )}
                    </Text>
                    {error ? (
                        <Text style={styles.error} accessibilityRole="alert" testID="feedback-error">
                            Couldn't send your feedback. Your message is still here. Try again.
                        </Text>
                    ) : null}
                    <TextInput
                        value={message}
                        onChangeText={setMessage}
                        editable={!sending}
                        autoFocus
                        multiline
                        disableFullscreenUI
                        maxLength={FEEDBACK_MAX_LENGTH}
                        placeholder="What's on your mind?"
                        placeholderTextColor={colors.tertiary}
                        keyboardAppearance={scheme}
                        textAlignVertical="top"
                        style={[styles.input, compact && styles.inputCompact]}
                        accessibilityLabel="Feedback"
                        testID="feedback-message"
                    />
                    <Pressable44
                        onPress={() => void send()}
                        disabled={!canSend}
                        accessibilityState={{ disabled: !canSend, busy: sending }}
                        pressedBackground={colors.inkHover}
                        style={[
                            styles.send,
                            compact && styles.sendCompact,
                            { backgroundColor: canSend ? colors.ink : colors.disabledFill },
                        ]}
                        testID="feedback-send"
                    >
                        {sending ? (
                            <ActivityIndicator color={colors.onDisabled} accessibilityLabel="Sending feedback" />
                        ) : (
                            <Text style={[styles.sendText, !canSend && styles.sendTextDisabled]}>Send</Text>
                        )}
                    </Pressable44>
                </Animated.ScrollView>
            </GestureDetector>
        </BottomSheet>
    )
}

const useStyles = createStyles(({ colors }) => ({
    content: {
        flexShrink: 1,
        minHeight: 0,
    },
    error: {
        ...type.metaSmall,
        color: colors.orange,
        marginTop: 8,
        paddingHorizontal: 4,
    },
    title: {
        ...type.sheetTitle,
        color: colors.ink,
        marginTop: 18,
        paddingHorizontal: 4,
    },
    description: {
        ...type.metaSmall,
        color: colors.muted,
        marginTop: 6,
        paddingHorizontal: 4,
    },
    email: {
        color: colors.ink,
    },
    input: {
        ...inputReset,
        ...type.input,
        color: colors.ink,
        marginTop: 16,
        minHeight: 140,
        maxHeight: 240,
        paddingHorizontal: 14,
        paddingTop: 12,
        paddingBottom: 12,
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.background,
    },
    inputCompact: {
        marginTop: 8,
        minHeight: 44,
        maxHeight: 88,
        paddingTop: 8,
        paddingBottom: 8,
    },
    send: {
        marginTop: 16,
        height: 52,
        borderRadius: radii.pill,
        alignItems: 'center',
        justifyContent: 'center',
    },
    sendCompact: {
        marginTop: 8,
        height: 44,
    },
    sendText: {
        ...type.button,
        color: colors.onInk,
    },
    sendTextDisabled: {
        color: colors.onDisabled,
    },
}))
