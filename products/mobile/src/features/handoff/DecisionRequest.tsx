import { type ReactElement, useState } from 'react'
import { Text, View } from 'react-native'

import type { DecisionAnswerInput, DecisionQuestion } from '@/model/types'
import { ChevronRightIcon } from '@/ui/icons/ChevronRightIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, type } from '@/ui/tokens'

import { useSheetFunnel } from '../report/reportAnalytics'
import { DecisionSheet } from './DecisionSheet'
import { handoffEntry } from './handoffStore'

interface DecisionRequestProps {
    question: DecisionQuestion
    /** Set on the report screen. Task chat leaves it out and sends no sheet events. */
    reportId?: string
    pending: boolean
    onAnswer: (input: DecisionAnswerInput) => void
    notice?: string
}

export function DecisionRequest({ question, reportId, pending, onAnswer, notice }: DecisionRequestProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const [open, setOpen] = useState(false)
    const sheets = useSheetFunnel(reportId)
    // An answer removes this request, so the sheet unmounts without `onClose`. Only a close the user makes calls it.
    const openSheet = (): void => {
        const kind = reportId ? handoffEntry(reportId).live?.pending?.kind : undefined
        sheets.opened('decision', 'action_bar', { kind: kind ?? 'unknown' })
        setOpen(true)
    }
    const closeSheet = (): void => {
        sheets.closed()
        setOpen(false)
    }
    return (
        <View>
            <Pressable44
                onPress={openSheet}
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
                onClose={closeSheet}
                question={question}
                pending={pending}
                onAnswer={onAnswer}
                notice={notice}
            />
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    row: { minHeight: 44, flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 12 },
    title: { ...type.metaSmall, fontWeight: '600', color: colors.orange, flex: 1 },
    link: { ...type.meta, color: colors.orange },
}))
