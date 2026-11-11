import { type ReactElement, useMemo, useState } from 'react'
import { Keyboard, ScrollView, Text, TextInput, useWindowDimensions, View } from 'react-native'
import { Gesture, GestureDetector } from 'react-native-gesture-handler'
import { useReanimatedKeyboardAnimation } from 'react-native-keyboard-controller'
import Animated, { useAnimatedStyle } from 'react-native-reanimated'

import { BottomSheet } from '@/ui/BottomSheet'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { inputReset, radii, type } from '@/ui/tokens'

interface ChatFeedbackSheetProps {
    onClose: () => void
    onSubmit: (text: string) => void
}

export function ChatFeedbackSheet({ onClose, onSubmit }: ChatFeedbackSheetProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const [text, setText] = useState('')
    const { height } = useWindowDimensions()
    const keyboard = useReanimatedKeyboardAnimation()
    const scrollGesture = useMemo(() => Gesture.Native(), [])
    const keyboardStyle = useAnimatedStyle(() => ({ paddingBottom: Math.max(-keyboard.height.value, 0) }))
    const contentStyle = useAnimatedStyle(() => ({ maxHeight: Math.max((height + keyboard.height.value) * 0.8, 140) }))
    const close = (): void => {
        Keyboard.dismiss()
        onClose()
    }

    return (
        <BottomSheet
            visible
            onClose={close}
            scrollGesture={scrollGesture}
            accessibilityLabel="Answer feedback"
            testID="chat-feedback-sheet"
        >
            <Animated.View style={keyboardStyle}>
                <Animated.View style={contentStyle}>
                    <GestureDetector gesture={scrollGesture}>
                        <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={styles.content}>
                            <Text style={styles.title} accessibilityRole="header">
                                What could be better?
                            </Text>
                            <Text style={styles.description}>
                                Your thumbs-down is saved. Add a comment if you'd like.
                            </Text>
                            <TextInput
                                accessibilityLabel="Feedback about this answer"
                                placeholder="Help us improve PostHog AI"
                                placeholderTextColor={colors.tertiary}
                                multiline
                                value={text}
                                onChangeText={setText}
                                style={[styles.input, inputReset]}
                                textAlignVertical="top"
                                autoFocus
                                testID="chat-feedback-input"
                            />
                            <View style={styles.buttons}>
                                <Pressable44
                                    onPress={close}
                                    style={[styles.button, styles.skip]}
                                    pressedBackground={colors.sunken}
                                >
                                    <Text style={styles.skipText}>Skip</Text>
                                </Pressable44>
                                <Pressable44
                                    onPress={() => {
                                        if (text.trim()) {
                                            Keyboard.dismiss()
                                            onSubmit(text.trim())
                                        }
                                    }}
                                    disabled={!text.trim()}
                                    accessibilityState={{ disabled: !text.trim() }}
                                    style={[styles.button, styles.submit, !text.trim() && styles.disabled]}
                                    pressedBackground={colors.inkHover}
                                    testID="chat-feedback-submit"
                                >
                                    <Text style={styles.submitText}>Send feedback</Text>
                                </Pressable44>
                            </View>
                        </ScrollView>
                    </GestureDetector>
                </Animated.View>
            </Animated.View>
        </BottomSheet>
    )
}

const useStyles = createStyles(({ colors }) => ({
    content: { paddingTop: 20, gap: 16 },
    title: { ...type.sheetTitle, color: colors.ink },
    description: { ...type.bodySmall, color: colors.muted },
    input: {
        ...type.body,
        color: colors.ink,
        backgroundColor: colors.sunken,
        borderRadius: radii.card,
        minHeight: 100,
        maxHeight: 180,
        padding: 12,
    },
    buttons: { flexDirection: 'row', gap: 12 },
    button: { flex: 1, minHeight: 48, borderRadius: radii.pill, alignItems: 'center', justifyContent: 'center' },
    skip: { borderWidth: 1, borderColor: colors.border },
    skipText: { ...type.buttonSmall, color: colors.ink },
    submit: { backgroundColor: colors.ink },
    submitText: { ...type.buttonSmall, color: colors.onInk },
    disabled: { opacity: 0.4 },
}))
