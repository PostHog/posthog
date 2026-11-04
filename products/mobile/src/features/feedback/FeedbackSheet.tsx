import { type ReactElement, useEffect, useRef, useState } from 'react'
import { Text, TextInput, View } from 'react-native'
import { useReanimatedKeyboardAnimation } from 'react-native-keyboard-controller'
import { BottomSheet } from '@/ui/BottomSheet'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useTheme } from '@/ui/theme'
import { inputReset, radii, type } from '@/ui/tokens'
import { useSceneDimensions } from '@/ui/useSceneDimensions'

import { FEEDBACK_MAX_LENGTH, feedbackDismissed, feedbackShown, sendFeedback } from './feedbackSurvey'

interface FeedbackSheetProps {
    visible: boolean
    /** Where the team replies. The sheet shows it next to the promise to follow up. */
    email: string
    onClose: () => void
    onSent: () => void
}

export function FeedbackSheet({ visible, email, onClose, onSent }: FeedbackSheetProps): ReactElement {
    const styles = useStyles()
    const { colors, scheme } = useTheme()
    const { height } = useSceneDimensions()
    const compact = height < 480
    const keyboard = useReanimatedKeyboardAnimation()
    const [message, setMessage] = useState('')
    // The sheet stays pressable while it animates out, so a second tap must not send again or count as a dismissal.
    const sent = useRef(false)

    useEffect(() => {
        if (visible) {
            setMessage('')
            sent.current = false
            feedbackShown()
        }
    }, [visible])

    const trimmed = message.trim()
    const canSend = trimmed.length > 0

    const dismiss = (): void => {
        if (!sent.current) {
            feedbackDismissed()
        }
        onClose()
    }
    const send = (): void => {
        if (!canSend || sent.current) {
            return
        }
        sent.current = true
        sendFeedback(trimmed, email)
        onSent()
    }

    return (
        <BottomSheet
            visible={visible}
            onClose={dismiss}
            paddingHorizontal={20}
            keyboardHeight={keyboard.height}
            accessibilityLabel="Send feedback"
            testID="feedback-sheet"
        >
            <View style={styles.content}>
                <Text style={styles.title} accessibilityRole="header">
                    Send feedback
                </Text>
                {compact ? null : (
                    <Text style={styles.description} testID="feedback-description">
                        Share ideas, bugs, or anything else on your mind. Your message goes straight to the PostHog
                        team, and we'll follow up by email at <Text style={styles.email}>{email}</Text>.
                    </Text>
                )}
                <TextInput
                    value={message}
                    onChangeText={setMessage}
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
                    onPress={send}
                    disabled={!canSend}
                    accessibilityState={{ disabled: !canSend }}
                    pressedBackground={colors.inkHover}
                    style={[
                        styles.send,
                        compact && styles.sendCompact,
                        { backgroundColor: canSend ? colors.ink : colors.disabledFill },
                    ]}
                    testID="feedback-send"
                >
                    <Text style={[styles.sendText, !canSend && styles.sendTextDisabled]}>Send</Text>
                </Pressable44>
            </View>
        </BottomSheet>
    )
}

const useStyles = createStyles(({ colors }) => ({
    content: {
        flexShrink: 1,
        minHeight: 0,
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
