import { type ReactElement, useMemo, useRef } from 'react'
import { ScrollView, Text, useWindowDimensions } from 'react-native'
import { Gesture, GestureDetector } from 'react-native-gesture-handler'
import { useReanimatedKeyboardAnimation } from 'react-native-keyboard-controller'
import Animated, { useAnimatedStyle } from 'react-native-reanimated'

import type { DecisionAnswerInput, DecisionQuestion } from '@/model/types'
import { BottomSheet } from '@/ui/BottomSheet'
import { createStyles } from '@/ui/theme'
import { type } from '@/ui/tokens'

import { DecisionCard } from './DecisionCard'
import { SheetPageHeader } from './SheetPageHeader'

interface DecisionSheetProps {
    visible: boolean
    onClose: () => void
    question: DecisionQuestion
    pending: boolean
    onAnswer: (input: DecisionAnswerInput) => void
    notice?: string
}

export function DecisionSheet({
    visible,
    onClose,
    question,
    pending,
    onAnswer,
    notice,
}: DecisionSheetProps): ReactElement {
    const styles = useStyles()
    const { height } = useWindowDimensions()
    const keyboard = useReanimatedKeyboardAnimation()
    const scroll = useRef<ScrollView>(null)
    const replyFocused = useRef(false)
    const listGesture = useMemo(() => Gesture.Native(), [])
    const keyboardStyle = useAnimatedStyle(() => ({ paddingBottom: Math.max(-keyboard.height.value, 0) }))
    const contentStyle = useAnimatedStyle(() => ({ maxHeight: Math.max(height * 0.6 + keyboard.height.value, 120) }))
    return (
        <BottomSheet
            visible={visible}
            onClose={onClose}
            scrollGesture={listGesture}
            accessibilityLabel="Needs your answer"
            testID="decision-sheet"
        >
            <Animated.View style={keyboardStyle}>
                <SheetPageHeader title="Needs your answer" onBack={onClose} testID="decision-sheet" />
                {notice ? (
                    <Text style={styles.notice} accessibilityRole="alert">
                        {notice}
                    </Text>
                ) : null}
                <Animated.View style={[styles.content, contentStyle]}>
                    <GestureDetector gesture={listGesture}>
                        <ScrollView
                            ref={scroll}
                            keyboardShouldPersistTaps="handled"
                            style={styles.scroll}
                            onLayout={() => {
                                if (replyFocused.current) {
                                    scroll.current?.scrollToEnd({ animated: false })
                                }
                            }}
                            testID="decision-sheet-scroll"
                        >
                            <DecisionCard
                                key={question.id}
                                question={question}
                                pending={pending}
                                onAnswer={onAnswer}
                                onReplyFocus={() => {
                                    replyFocused.current = true
                                    scroll.current?.scrollToEnd({ animated: true })
                                }}
                                onReplyBlur={() => {
                                    replyFocused.current = false
                                }}
                            />
                        </ScrollView>
                    </GestureDetector>
                </Animated.View>
            </Animated.View>
        </BottomSheet>
    )
}

const useStyles = createStyles(({ colors }) => ({
    content: { marginTop: 8 },
    scroll: { flexGrow: 0 },
    notice: { ...type.metaSmall, color: colors.orange, paddingHorizontal: 4, marginTop: 6 },
}))
