import { type ReactElement, useState } from 'react'
import { Text, TextInput, View } from 'react-native'

import { ChatMarkdown } from '@/features/chat/ChatMarkdown'
import type { DecisionAnswerInput, DecisionQuestion } from '@/model/types'
import { ArrowUpIcon } from '@/ui/icons/ArrowUpIcon'
import { ChevronRightIcon } from '@/ui/icons/ChevronRightIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useTheme } from '@/ui/theme'
import { iconSizes, inputReset, radii, type } from '@/ui/tokens'

interface DecisionCardProps {
    question: DecisionQuestion
    onAnswer: (input: DecisionAnswerInput) => void
    pending: boolean
    onReplyFocus?: () => void
    onReplyBlur?: () => void
}

export function DecisionCard({
    question,
    onAnswer,
    pending,
    onReplyFocus,
    onReplyBlur,
}: DecisionCardProps): ReactElement {
    const { colors, scheme } = useTheme()
    const styles = useStyles()
    const [reply, setReply] = useState('')
    const canSend = reply.trim().length > 0 && !pending

    const sendReply = (): void => {
        const text = reply.trim()
        if (!text || pending) {
            return
        }
        onAnswer({ questionId: question.id, text })
    }

    return (
        <View style={styles.card} testID="decision-card">
            <ChatMarkdown text={question.question} />
            {question.details ? (
                <View style={styles.details} testID="decision-request-details">
                    <Text style={styles.optionTitle}>Request details</Text>
                    <Text selectable style={styles.requestText}>
                        {question.details}
                    </Text>
                </View>
            ) : null}
            {question.options.length > 0 ? (
                <View style={styles.options}>
                    {question.options.map((option) => (
                        <Pressable44
                            key={option.id}
                            onPress={() =>
                                onAnswer({ questionId: question.id, optionId: option.id, text: option.title })
                            }
                            disabled={pending}
                            pressedBackground={colors.pressed}
                            style={styles.option}
                            testID={`decision-option-${option.id}`}
                        >
                            <View style={styles.optionBody}>
                                <Text style={styles.optionTitle}>{option.title}</Text>
                                {option.meta ? <Text style={styles.optionMeta}>{option.meta}</Text> : null}
                            </View>
                            <ChevronRightIcon size={iconSizes.inline} color={colors.disabled} strokeWidth={2.8} />
                        </Pressable44>
                    ))}
                </View>
            ) : null}
            <View style={styles.reply}>
                <TextInput
                    value={reply}
                    onChangeText={setReply}
                    onFocus={onReplyFocus}
                    onBlur={onReplyBlur}
                    onSubmitEditing={sendReply}
                    placeholder={question.options.length > 0 ? 'Or type your answer' : 'Type your reply'}
                    placeholderTextColor={colors.tertiary}
                    keyboardAppearance={scheme}
                    returnKeyType="send"
                    style={styles.input}
                    accessibilityLabel="Your answer"
                />
                <Pressable44
                    onPress={sendReply}
                    disabled={!canSend}
                    accessibilityLabel="Send"
                    accessibilityState={{ disabled: !canSend, busy: pending }}
                    style={[styles.send, { backgroundColor: canSend ? colors.accent : colors.disabledFill }]}
                    hitSlop={4}
                >
                    <ArrowUpIcon size={iconSizes.control} color={canSend ? colors.onAccent : colors.onDisabled} />
                </Pressable44>
            </View>
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    card: {
        gap: 14,
        paddingHorizontal: 4,
        paddingBottom: 8,
    },
    details: {
        gap: 8,
        padding: 12,
        borderRadius: radii.option,
        backgroundColor: colors.background,
    },
    requestText: {
        ...type.mono,
        color: colors.ink,
    },
    options: {
        gap: 8,
    },
    option: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        minHeight: 60,
        paddingVertical: 10,
        paddingHorizontal: 16,
        borderRadius: radii.option,
        backgroundColor: colors.background,
    },
    optionBody: {
        flex: 1,
        minWidth: 0,
    },
    optionTitle: {
        ...type.bodyStrong,
        color: colors.ink,
    },
    optionMeta: {
        fontSize: 13,
        lineHeight: 18.2,
        color: colors.muted,
        marginTop: 2,
    },
    reply: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
        height: 48,
        borderRadius: radii.pill,
        backgroundColor: colors.background,
        borderWidth: 1,
        borderColor: colors.hairline,
        paddingTop: 4,
        paddingBottom: 4,
        paddingRight: 4,
        paddingLeft: 18,
    },
    input: {
        ...inputReset,
        flex: 1,
        minWidth: 0,
        ...type.input,
        color: colors.ink,
        paddingVertical: 0,
    },
    send: {
        width: 40,
        height: 40,
        borderRadius: 20,
        alignItems: 'center',
        justifyContent: 'center',
    },
}))
