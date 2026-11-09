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
    onRetryNotice?: () => void
    noticePending?: boolean
    onDismissNotice: () => void
    onReconnect?: () => void
}

export function SessionDecisionPanel({
    decision,
    notice,
    pending,
    onAnswer,
    onDismissNotice,
    onReconnect,
    onRetryNotice,
    noticePending,
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
                    {onReconnect ? (
                        <Pressable44
                            onPress={onReconnect}
                            accessibilityLabel="Reconnect to the agent"
                            testID="session-reconnect"
                        >
                            <Text style={styles.reconnectText}>Reconnect</Text>
                        </Pressable44>
                    ) : null}
                    {onRetryNotice ? (
                        <Pressable44
                            onPress={onRetryNotice}
                            disabled={noticePending}
                            accessibilityLabel="Retry saving draft"
                            accessibilityState={{ disabled: noticePending, busy: noticePending }}
                            style={styles.retry}
                            testID="chat-draft-retry"
                        >
                            <Text style={styles.retryText}>{noticePending ? 'Saving…' : 'Retry save'}</Text>
                        </Pressable44>
                    ) : (
                        <Pressable44
                            onPress={onDismissNotice}
                            accessibilityLabel="Dismiss"
                            style={styles.close}
                            hitSlop={10}
                        >
                            <CloseIcon size={iconSizes.inline} color={colors.orange} />
                        </Pressable44>
                    )}
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
    reconnectText: {
        ...type.meta,
        color: colors.orange,
    },
    retry: { paddingHorizontal: 8 },
    retryText: { ...type.meta, color: colors.orange },
    close: {
        width: 24,
        height: 24,
        alignItems: 'center',
        justifyContent: 'center',
    },
}))
