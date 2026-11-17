import { Fragment, memo, type ReactElement, type ReactNode, useCallback, useEffect, useMemo, useRef } from 'react'
import type { ScrollViewInstance } from 'react-native'
import { type NativeScrollEvent, type NativeSyntheticEvent, ScrollView, Text, View } from 'react-native'
import { PullRequestCard } from '@/features/handoff/PullRequestCard'
import { formatMonthDay, isoDay } from '@/lib/dates'
import { WarningIcon } from '@/ui/icons/WarningIcon'
import { LoadingView, StateView } from '@/ui/StateView'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, type } from '@/ui/tokens'
import { ChatChartResources, ChatChartRow, useChatChartViewport } from '../ChatChartResources'
import { ChatErrorBubble } from '../ChatErrorBubble'
import { ChatMarkdown } from '../ChatMarkdown'
import { ChatProgressLine } from '../ChatProgressLine'
import { ChatVisualization } from '../ChatVisualization'
import { CopyMessageButton } from '../CopyMessageButton'
import { type ChatFeedbackContext, type ChatReplyActions, chatReplyActions } from '../chatFeedback'
import { MessageFeedbackActions } from '../MessageFeedbackActions'
import { MessageTime } from '../MessageTime'
import { UserBubble } from '../UserBubble'
import { ActivityGroupRow } from './ActivityGroupRow'
import { NoticeRow } from './NoticeRow'
import { ProgressRow } from './ProgressRow'
import { currentTurnActivityIds, errorItemText, groupSessionItems, shouldShowRunError } from './sessionDisplay'
import type { Session, SessionAssistantItem, SessionDisplayItem, SessionErrorItem } from './types'

export type SessionThreadState = Pick<
    Session,
    | 'history'
    | 'items'
    | 'invocations'
    | 'phase'
    | 'stage'
    | 'decision'
    | 'pullRequests'
    | 'pullRequest'
    | 'runStatus'
    | 'runError'
>

interface SessionThreadProps {
    session: SessionThreadState
    onRetryHistory: () => void
    topInset?: number
    feedbackContext?: ChatFeedbackContext
}

const AssistantRow = memo(
    function AssistantRow({ item, actions }: { item: SessionAssistantItem; actions?: ChatReplyActions }): ReactElement {
        const styles = useStyles()
        const feedback = actions?.feedback
        return (
            <View style={actions ? undefined : styles.assistantWithoutActions} testID="session-assistant">
                <ChatMarkdown text={item.text} streaming={!item.complete} projectUrl={item.projectUrl} />
                {actions ? (
                    <View style={styles.actions}>
                        <CopyMessageButton text={item.copyText ?? item.text} messageRole="assistant" />
                        {feedback ? (
                            <MessageFeedbackActions
                                key={`${feedback.sessionId}:${feedback.traceId ?? feedback.turnIndex}`}
                                target={feedback}
                            />
                        ) : null}
                        <MessageTime timestamp={item.timestamp} />
                    </View>
                ) : null}
            </View>
        )
    },
    (previous, next) =>
        previous.item.text === next.item.text &&
        previous.item.copyText === next.item.copyText &&
        previous.item.timestamp === next.item.timestamp &&
        previous.item.complete === next.item.complete &&
        previous.item.projectUrl === next.item.projectUrl &&
        Boolean(previous.actions) === Boolean(next.actions) &&
        previous.actions?.feedback?.sessionId === next.actions?.feedback?.sessionId &&
        previous.actions?.feedback?.runtime === next.actions?.feedback?.runtime &&
        previous.actions?.feedback?.traceId === next.actions?.feedback?.traceId &&
        previous.actions?.feedback?.runId === next.actions?.feedback?.runId &&
        previous.actions?.feedback?.turnIndex === next.actions?.feedback?.turnIndex
)

const ErrorRow = memo(function ErrorRow({ item }: { item: SessionErrorItem }): ReactElement {
    return <ChatErrorBubble text={errorItemText(item)} />
})

const TurnEndRow = memo(function TurnEndRow(): ReactElement {
    const styles = useStyles()
    return <View style={styles.turnEnd} />
})

function statusLine(session: SessionThreadState): string | null {
    switch (session.phase) {
        case 'working':
            return session.stage ?? 'Thinking…'
        case 'reconnecting':
        case 'idle':
            return null
    }
}

export function SessionThread(props: SessionThreadProps): ReactElement {
    return (
        <ChatChartResources>
            <SessionThreadBody {...props} />
        </ChatChartResources>
    )
}

function SessionThreadBody({
    session,
    onRetryHistory,
    topInset = 0,
    feedbackContext,
}: SessionThreadProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const chartViewport = useChatChartViewport()
    const scroll = useRef<ScrollViewInstance>(null)
    const positioned = useRef(false)
    const following = useRef(true)
    const followFrame = useRef<number | null>(null)
    const animateFollow = useRef(false)
    const followToEnd = useCallback((animated: boolean): void => {
        if (!following.current) return
        animateFollow.current = followFrame.current === null ? animated : animateFollow.current && animated
        if (followFrame.current !== null) return
        followFrame.current = requestAnimationFrame(() => {
            followFrame.current = null
            if (!following.current || !scroll.current) return
            scroll.current.scrollToEnd({ animated: animateFollow.current })
            positioned.current = true
        })
    }, [])
    useEffect(
        () => () => {
            if (followFrame.current !== null) cancelAnimationFrame(followFrame.current)
        },
        []
    )
    const displayItems = useMemo(() => groupSessionItems(session.items), [session.items])
    const activeActivityIds = useMemo(() => currentTurnActivityIds(session.items), [session.items])
    const replyActions = useMemo(
        () => chatReplyActions(session.items, feedbackContext, session.phase),
        [session.items, feedbackContext, session.phase]
    )
    const pauseFollowing = useCallback((): void => {
        following.current = false
    }, [])
    const updateFollowing = (event: NativeSyntheticEvent<NativeScrollEvent>): void => {
        const { contentOffset, contentSize, layoutMeasurement } = event.nativeEvent
        following.current = contentSize.height - contentOffset.y - layoutMeasurement.height <= 24
    }

    if (session.history.status === 'loading') {
        positioned.current = false
        following.current = true
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
                return (
                    <UserBubble
                        key={item.id}
                        text={item.text}
                        timestamp={item.timestamp}
                        attachments={item.attachments}
                    />
                )
            case 'assistant':
                return <AssistantRow key={item.id} item={item} actions={replyActions.get(item.id)} />
            case 'visualization': {
                const feedback = replyActions.get(item.id)?.feedback
                return (
                    <ChatVisualization
                        key={item.id}
                        visualizationId={item.id}
                        query={item.query}
                        shortId={item.shortId}
                        title={item.title}
                        result={item.result}
                        webUrl={item.webUrl}
                    >
                        {(replyActions.has(item.id) && item.copyText) || feedback ? (
                            <View style={styles.actions}>
                                {replyActions.has(item.id) && item.copyText ? (
                                    <CopyMessageButton text={item.copyText} messageRole="assistant" />
                                ) : null}
                                {feedback ? <MessageFeedbackActions target={feedback} /> : null}
                            </View>
                        ) : null}
                    </ChatVisualization>
                )
            }
            case 'activity':
                return (
                    <ActivityGroupRow
                        key={item.id}
                        group={item}
                        invocations={session.invocations}
                        waitingToolCallId={session.decision?.toolCallId}
                        active={session.phase === 'working' && item.items.some((row) => activeActivityIds.has(row.id))}
                        onToggle={pauseFollowing}
                    />
                )
            case 'turn_end':
                return <TurnEndRow key={item.id} />
            case 'error':
                return <ErrorRow key={item.id} item={item} />
            case 'notice':
                return <NoticeRow key={item.id} item={item} onToggle={pauseFollowing} />
            case 'progress':
                return <ProgressRow key={item.id} item={item} />
        }
    }

    let previousDay: string | undefined
    const status = statusLine(session)
    const isEmpty = displayItems.length === 0 && !session.decision
    const pullRequests = session.pullRequests ?? (session.pullRequest ? [session.pullRequest] : [])

    return (
        <ScrollView
            ref={scroll}
            style={styles.scroll}
            contentContainerStyle={[styles.content, { paddingTop: topInset + 12 }]}
            scrollIndicatorInsets={{ top: topInset }}
            onLayout={(event) => {
                chartViewport.onLayout(event)
                followToEnd(false)
            }}
            onScroll={chartViewport.onScroll}
            scrollEventThrottle={100}
            onScrollBeginDrag={pauseFollowing}
            onScrollEndDrag={updateFollowing}
            onMomentumScrollEnd={updateFollowing}
            onContentSizeChange={() => {
                followToEnd(positioned.current)
            }}
            keyboardShouldPersistTaps="handled"
            keyboardDismissMode="interactive"
            testID="session-thread"
        >
            {isEmpty ? <Text style={styles.quiet}>The agent hasn't said anything yet.</Text> : null}
            {displayItems.map((item, index) => {
                const timestamp = item.kind === 'user' || item.kind === 'assistant' ? item.timestamp : undefined
                const date = timestamp ? new Date(timestamp) : null
                const day = date && Number.isFinite(date.getTime()) ? isoDay(date) : undefined
                const showDate = day !== undefined && day !== previousDay
                if (day) previousDay = day
                return (
                    <Fragment key={item.id}>
                        {showDate && date ? (
                            <Text style={styles.quiet} testID="chat-date">
                                {formatMonthDay(date)}, {date.getFullYear()}
                            </Text>
                        ) : null}
                        <ChatChartRow rowKey={item.id} index={index}>
                            {renderItem(item)}
                        </ChatChartRow>
                    </Fragment>
                )
            })}
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
    assistantWithoutActions: {
        // Markdown blocks end with a 10pt bottom margin; this keeps the thread gap even.
        marginBottom: -10,
    },
    actions: { flexDirection: 'row', alignItems: 'flex-start', flexWrap: 'wrap', gap: 12 },
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
