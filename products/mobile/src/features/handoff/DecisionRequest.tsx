import { type ReactElement, useState } from 'react'
import { StyleSheet, Text, View } from 'react-native'

import type { DecisionAnswerInput, DecisionQuestion } from '@/model/types'
import { ChevronRightIcon } from '@/ui/icons/ChevronRightIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { colors, iconSizes, type } from '@/ui/tokens'

import { DecisionSheet } from './DecisionSheet'

interface DecisionRequestProps {
    question: DecisionQuestion
    pending: boolean
    onAnswer: (input: DecisionAnswerInput) => void
    notice?: string
}

export function DecisionRequest({ question, pending, onAnswer, notice }: DecisionRequestProps): ReactElement {
    const [open, setOpen] = useState(false)
    return (
        <View>
            <Pressable44
                onPress={() => setOpen(true)}
                accessibilityLabel="Needs your answer. Read question"
                pressedBackground={colors.pressed}
                style={styles.row}
                testID="decision-request"
            >
                <Text style={styles.title}>Needs your answer</Text>
                <Text style={styles.link}>Read question</Text>
                <ChevronRightIcon size={iconSizes.inline} color={colors.orange} />
            </Pressable44>
            <DecisionSheet
                visible={open}
                onClose={() => setOpen(false)}
                question={question}
                pending={pending}
                onAnswer={onAnswer}
                notice={notice}
            />
        </View>
    )
}

const styles = StyleSheet.create({
    row: { minHeight: 44, flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 12 },
    title: { ...type.metaSmall, fontWeight: '600', color: colors.orange, flex: 1 },
    link: { ...type.meta, color: colors.orange },
})
