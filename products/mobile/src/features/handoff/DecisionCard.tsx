import { type ReactElement, useEffect, useState } from 'react'
import { StyleSheet, Text, TextInput, View } from 'react-native'
import Animated, { useAnimatedStyle, useReducedMotion, useSharedValue, withTiming } from 'react-native-reanimated'

import type { DecisionAnswerInput, DecisionQuestion } from '@/model/types'
import { Eyebrow } from '@/ui/Eyebrow'
import { ArrowUpIcon } from '@/ui/icons/ArrowUpIcon'
import { ChevronRightIcon } from '@/ui/icons/ChevronRightIcon'
import { ChevronUpIcon } from '@/ui/icons/ChevronUpIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { colors, inputReset, motion, prettyWrap, radii, shadows, type } from '@/ui/tokens'

interface DecisionCardProps {
    question: DecisionQuestion
    onAnswer: (input: DecisionAnswerInput) => void
    pending: boolean
    eyebrow?: string
}

export function DecisionCard({
    question,
    onAnswer,
    pending,
    eyebrow = 'NEEDS YOUR DECISION',
}: DecisionCardProps): ReactElement {
    const [collapsed, setCollapsed] = useState(false)
    const [reply, setReply] = useState('')
    const reduceMotion = useReducedMotion()
    const rotation = useSharedValue(0)

    useEffect(() => {
        rotation.value = withTiming(collapsed ? 180 : 0, { duration: reduceMotion ? 0 : motion.chevron })
    }, [collapsed, reduceMotion, rotation])

    const chevronStyle = useAnimatedStyle(() => ({ transform: [{ rotate: `${rotation.value}deg` }] }))
    const canSend = reply.trim().length > 0 && !pending

    const sendReply = (): void => {
        const text = reply.trim()
        if (!text || pending) {
            return
        }
        onAnswer({ questionId: question.id, text })
        setReply('')
    }

    return (
        <View style={[styles.card, shadows.card]} testID="decision-card">
            <Pressable44
                onPress={() => setCollapsed((value) => !value)}
                accessibilityLabel={collapsed ? 'Show the question' : 'Hide the question'}
                accessibilityState={{ expanded: !collapsed }}
                style={styles.header}
                hitSlop={4}
            >
                <View style={styles.headerLabel}>
                    <Eyebrow color={colors.orange} withDot>
                        {eyebrow}
                    </Eyebrow>
                </View>
                <Animated.View style={chevronStyle}>
                    <ChevronUpIcon size={16} color={colors.tertiary} />
                </Animated.View>
            </Pressable44>
            {collapsed ? null : (
                <>
                    <Text
                        style={[styles.question, prettyWrap]}
                        lineBreakStrategyIOS="standard"
                        // A reply card quotes the agent's last words, which can run long in the footer.
                        numberOfLines={question.options.length === 0 ? 6 : undefined}
                    >
                        {question.question}
                    </Text>
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
                                    <ChevronRightIcon size={14} color={colors.disabled} strokeWidth={2.8} />
                                </Pressable44>
                            ))}
                        </View>
                    ) : null}
                    <View style={styles.reply}>
                        <TextInput
                            value={reply}
                            onChangeText={setReply}
                            onSubmitEditing={sendReply}
                            placeholder={question.options.length > 0 ? 'Or type your answer' : 'Type your reply'}
                            placeholderTextColor={colors.tertiary}
                            returnKeyType="send"
                            style={styles.input}
                            accessibilityLabel="Your answer"
                        />
                        <Pressable44
                            onPress={sendReply}
                            disabled={!canSend}
                            accessibilityLabel="Send"
                            accessibilityState={{ disabled: !canSend, busy: pending }}
                            style={[styles.send, { backgroundColor: canSend ? colors.orange : colors.border }]}
                            hitSlop={4}
                        >
                            <ArrowUpIcon size={16} color={colors.white} />
                        </Pressable44>
                    </View>
                </>
            )}
        </View>
    )
}

const styles = StyleSheet.create({
    card: {
        gap: 14,
        padding: 16,
        borderRadius: radii.softCard,
        backgroundColor: colors.white,
        borderWidth: 1,
        borderColor: colors.hairline,
    },
    header: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 10,
        minHeight: 28,
    },
    headerLabel: {
        flex: 1,
        minWidth: 0,
    },
    question: {
        fontSize: 17,
        lineHeight: 23.8,
        fontWeight: '600',
        letterSpacing: -0.17,
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
        fontSize: 16,
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
})
