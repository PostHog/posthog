import type { ReactElement } from 'react'
import { Text, View } from 'react-native'

import { DecisionRequest } from '@/features/handoff/DecisionRequest'
import type { DecisionAnswerInput } from '@/model/types'
import { CloseIcon } from '@/ui/icons/CloseIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, type } from '@/ui/tokens'

import type { SessionDecision } from './types'

interface SessionDecisionPanelProps {
    decision: SessionDecision | undefined
    notice: string | undefined
    pending: boolean
    onAnswer: (input: DecisionAnswerInput) => void
    onDismissNotice: () => void
}

export function SessionDecisionPanel({
    decision,
    notice,
    pending,
    onAnswer,
    onDismissNotice,
}: SessionDecisionPanelProps): ReactElement | null {
    const colors = useColors()
    const styles = useStyles()
    if (!decision && !notice) {
        return null
    }
    return (
        <View style={styles.panel}>
            {notice ? (
                <View style={styles.notice} testID="session-decision-notice">
                    <Text style={styles.noticeText}>{notice}</Text>
                    <Pressable44
                        onPress={onDismissNotice}
                        accessibilityLabel="Dismiss"
                        style={styles.close}
                        hitSlop={10}
                    >
                        <CloseIcon size={iconSizes.inline} color={colors.orange} />
                    </Pressable44>
                </View>
            ) : null}
            {decision ? (
                <View testID="session-decision">
                    <DecisionRequest
                        question={decision.question}
                        onAnswer={onAnswer}
                        pending={pending}
                        notice={notice}
                    />
                </View>
            ) : null}
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    panel: {
        marginHorizontal: 10,
        gap: 8,
    },
    notice: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
        paddingLeft: 6,
    },
    noticeText: {
        ...type.meta,
        color: colors.orange,
        flex: 1,
    },
    close: {
        width: 24,
        height: 24,
        alignItems: 'center',
        justifyContent: 'center',
    },
}))
