import type { ReactElement } from 'react'
import { Text, View } from 'react-native'

import { ChatErrorNotice } from '@/features/chat/ChatErrorNotice'
import { DecisionRequest } from '@/features/handoff/DecisionRequest'
import type { DecisionAnswerInput } from '@/model/types'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles } from '@/ui/theme'
import { type } from '@/ui/tokens'

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
    const styles = useStyles()
    if (!decision && !notice) {
        return null
    }
    return (
        <View style={styles.panel}>
            {notice ? (
                <ChatErrorNotice
                    message={notice}
                    onDismiss={onRetryNotice ? undefined : onDismissNotice}
                    testID="session-decision-notice"
                    actions={
                        onReconnect || onRetryNotice ? (
                            <>
                                {onReconnect ? (
                                    <Pressable44
                                        onPress={onReconnect}
                                        accessibilityLabel="Reconnect to the agent"
                                        style={styles.action}
                                        testID="session-reconnect"
                                    >
                                        <Text style={styles.actionText}>Reconnect</Text>
                                    </Pressable44>
                                ) : null}
                                {onRetryNotice ? (
                                    <Pressable44
                                        onPress={onRetryNotice}
                                        disabled={noticePending}
                                        accessibilityLabel="Retry saving draft"
                                        accessibilityState={{ disabled: noticePending, busy: noticePending }}
                                        style={styles.action}
                                        testID="chat-draft-retry"
                                    >
                                        <Text style={styles.actionText}>
                                            {noticePending ? 'Saving…' : 'Retry save'}
                                        </Text>
                                    </Pressable44>
                                ) : null}
                            </>
                        ) : undefined
                    }
                />
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
        marginBottom: 8,
        gap: 8,
    },
    action: {
        minHeight: 44,
        paddingHorizontal: 8,
        justifyContent: 'center',
    },
    actionText: { ...type.meta, color: colors.orange },
}))
