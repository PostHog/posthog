import { memo, type ReactElement, type ReactNode, useMemo, useRef } from 'react'
import { ScrollView, Text, View } from 'react-native'

import { PullRequestCard } from '@/features/handoff/PullRequestCard'
import { WarningIcon } from '@/ui/icons/WarningIcon'
import { LoadingView, StateView } from '@/ui/StateView'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, type } from '@/ui/tokens'

import { ChatErrorBubble } from '../ChatErrorBubble'
import { ChatMarkdown } from '../ChatMarkdown'
import { ChatProgressLine } from '../ChatProgressLine'
import { UserBubble } from '../UserBubble'
import { ActivityGroupRow } from './ActivityGroupRow'
import { NoticeRow } from './NoticeRow'
import { ProgressRow } from './ProgressRow'
import { errorItemText, groupSessionItems, shouldShowRunError } from './sessionDisplay'
import type { Session, SessionAssistantItem, SessionDisplayItem, SessionErrorItem } from './types'

interface SessionThreadProps {
    session: Session
    onRetryHistory: () => void
    topInset?: number
}

const AssistantRow = memo(function AssistantRow({ item }: { item: SessionAssistantItem }): ReactElement {
    const styles = useStyles()
    return (
        <View style={styles.assistant} testID="session-assistant">
            <ChatMarkdown text={item.text} streaming={!item.complete} />
        </View>
    )
})

const ErrorRow = memo(function ErrorRow({ item }: { item: SessionErrorItem }): ReactElement {
    return <ChatErrorBubble text={errorItemText(item)} />
})

const TurnEndRow = memo(function TurnEndRow(): ReactElement {
    const styles = useStyles()
    return <View style={styles.turnEnd} />
})

function statusLine(session: Session): string | null {
    switch (session.phase) {
        case 'working':
            return session.stage ?? 'Thinking…'
        case 'reconnecting':
            return 'Reconnecting…'
        case 'idle':
            return null
    }
}

export function SessionThread({ session, onRetryHistory, topInset = 0 }: SessionThreadProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const scroll = useRef<ScrollView>(null)
    const positioned = useRef(false)
    const displayItems = useMemo(() => groupSessionItems(session.items), [session.items])

    if (session.history.status === 'loading') {
        positioned.current = false
        return (
            <View style={[styles.scroll, { paddingTop: topInset }]}>
                <LoadingView label="Loading session" />
            </View>
        )
    }
    if (session.history.status === 'error') {
        return (
            <View style={[styles.scroll, { paddingTop: topInset }]}>
                <StateView
                    icon={<WarningIcon size={iconSizes.empty} color={colors.orange} />}
                    title="Couldn't load this session"
                    message={session.history.error?.message}
                    actionLabel="Try again"
                    onAction={onRetryHistory}
                    testID="session-history-error"
                />
            </View>
        )
    }

    const renderItem = (item: SessionDisplayItem): ReactNode => {
        switch (item.kind) {
            case 'user':
                return <UserBubble key={item.id} text={item.text} attachments={item.attachments} />
            case 'assistant':
                return <AssistantRow key={item.id} item={item} />
            case 'activity':
                return (
                    <ActivityGroupRow
                        key={item.id}
                        group={item}
                        invocations={session.invocations}
                        waitingToolCallId={session.decision?.toolCallId}
                    />
                )
            case 'turn_end':
                return <TurnEndRow key={item.id} />
            case 'error':
                return <ErrorRow key={item.id} item={item} />
            case 'notice':
                return <NoticeRow key={item.id} item={item} />
            case 'progress':
                return <ProgressRow key={item.id} item={item} />
        }
    }

    const status = statusLine(session)
    const isEmpty = displayItems.length === 0 && !session.decision
    const pullRequests = session.pullRequests ?? (session.pullRequest ? [session.pullRequest] : [])

    return (
        <ScrollView
            ref={scroll}
            style={styles.scroll}
            contentContainerStyle={[styles.content, { paddingTop: topInset + 12 }]}
            scrollIndicatorInsets={{ top: topInset }}
            onContentSizeChange={() => {
                scroll.current?.scrollToEnd({ animated: positioned.current })
                positioned.current = true
            }}
            keyboardShouldPersistTaps="handled"
            keyboardDismissMode="interactive"
            testID="session-thread"
        >
            {isEmpty ? <Text style={styles.quiet}>The agent hasn't said anything yet.</Text> : null}
            {displayItems.map(renderItem)}
            {pullRequests.length > 0 ? <PullRequestCard pullRequests={pullRequests} /> : null}
            {status ? <ChatProgressLine text={status} /> : null}
            {shouldShowRunError(session.items, session.runStatus, session.runError) ? (
                <ChatErrorBubble text={session.runError} />
            ) : null}
            {session.runStatus === 'cancelled' ? <Text style={styles.quiet}>Run stopped</Text> : null}
        </ScrollView>
    )
}

const useStyles = createStyles(({ colors }) => ({
    scroll: {
        flex: 1,
    },
    content: {
        paddingHorizontal: 20,
        paddingVertical: 12,
        gap: 14,
    },
    assistant: {
        // Markdown blocks end with a 10pt bottom margin; this keeps the thread gap even.
        marginBottom: -10,
    },
    turnEnd: {
        height: 8,
    },
    quiet: {
        ...type.meta,
        color: colors.muted,
        textAlign: 'center',
        paddingVertical: 8,
    },
}))
