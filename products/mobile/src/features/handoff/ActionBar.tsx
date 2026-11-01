import type { ReactElement } from 'react'
import { Text, View } from 'react-native'
import { KeyboardStickyView } from 'react-native-keyboard-controller'

import type { ActionBarState, ReportActions, ReportView } from '@/model/types'
import { ComposeIcon } from '@/ui/icons/ComposeIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useTheme } from '@/ui/theme'
import { iconSizes, layout, radii, type } from '@/ui/tokens'
import { bottomOffset, useScreenInsets } from '@/ui/useScreenInsets'

import { ActionPill } from './ActionPill'
import { AgentStatusCard } from './AgentStatusCard'
import { DecisionRequest } from './DecisionRequest'
import { HandoffSplitButton } from './HandoffSplitButton'
import { useHandoffEntry } from './hooks'
import { PullRequestCard } from './PullRequestCard'
import type { HandoffAnswer } from './types'

export type TaskChatEntry = 'status_card' | 'decided_card' | 'pr_card'

interface ActionBarProps {
    report: ReportView
    state: ActionBarState
    answer?: HandoffAnswer
    notice?: string
    actions: ReportActions
    onOpenHandoff: () => void
    onReassign: () => void
    onResolve: () => void
    onDismiss: () => void
    onChat: () => void
    onTaskChat?: (entry: TaskChatEntry) => void
}

export function ActionBar({
    report,
    state,
    answer,
    notice,
    actions,
    onOpenHandoff,
    onReassign,
    onResolve,
    onDismiss,
    onChat,
    onTaskChat,
}: ActionBarProps): ReactElement {
    const { colors, shadows } = useTheme()
    const styles = useStyles()
    const insets = useScreenInsets()
    const unstartedTaskId =
        useHandoffEntry(report.id)?.unstartedTaskId ??
        (report.task?.status === 'not_started' && !report.task.runId ? report.task.taskId : undefined)
    const assignee = report.work.assignee
    const canRetry = Boolean(
        unstartedTaskId &&
            !report.task?.runId &&
            (!assignee || (assignee.kind === 'task' && assignee.taskId === unstartedTaskId)) &&
            report.canAct !== false &&
            report.status !== 'resolved' &&
            report.work.state !== 'done'
    )
    const showHandoff = state.showHandoff || canRetry
    const hasPullRequests = state.pullRequests.length > 0
    const activity = state.activity
    const taskChatFrom = (entry: TaskChatEntry): (() => void) | undefined =>
        onTaskChat && !hasPullRequests ? () => onTaskChat(entry) : undefined
    const footerState = state.request
        ? 'decision'
        : hasPullRequests
          ? 'pr_ready'
          : state.answer
            ? 'decided'
            : showHandoff
              ? 'idle'
              : activity
                ? 'handed'
                : 'resolved'
    const activityContent = (
        <>
            {activity ? (
                <AgentStatusCard
                    title={activity.title}
                    meta={activity.meta}
                    tone={activity.tone}
                    onOpenChat={taskChatFrom('status_card')}
                    testID={activity.tone === 'stopped' ? 'agent-stopped-card' : 'agent-status-card'}
                />
            ) : null}
            {state.answer ? (
                <AgentStatusCard
                    title={state.answer.text}
                    meta={state.answer.meta}
                    tone="idle"
                    onOpenChat={taskChatFrom('decided_card')}
                    {...(answer?.canUndo ? { onUndo: () => void actions.undoDecision() } : {})}
                    testID="decided-card"
                />
            ) : null}
            {state.request ? (
                <DecisionRequest
                    key={state.request.id}
                    question={state.request}
                    reportId={report.id}
                    pending={actions.pending.answer}
                    onAnswer={(input) => void actions.answerDecision(input)}
                    notice={notice}
                />
            ) : null}
        </>
    )

    return (
        <KeyboardStickyView offset={{ opened: insets.bottom }}>
            <View
                style={[styles.bar, { paddingBottom: bottomOffset(insets, 38) }]}
                testID={`action-bar-${footerState}`}
            >
                {notice ? (
                    <Text style={styles.notice} accessibilityRole="alert" testID="handoff-notice">
                        {notice}
                    </Text>
                ) : null}
                {hasPullRequests ? (
                    <PullRequestCard
                        pullRequests={state.pullRequests}
                        onTaskChat={onTaskChat ? () => onTaskChat('pr_card') : undefined}
                        reportId={report.id}
                    >
                        {activity || state.request || state.answer ? activityContent : null}
                    </PullRequestCard>
                ) : activity || state.request || state.answer ? (
                    <View style={styles.panel}>{activityContent}</View>
                ) : null}
                {showHandoff ? (
                    <HandoffSplitButton
                        report={report}
                        onHandOff={() => void actions.handOff()}
                        onOpenPicker={onOpenHandoff}
                        pending={actions.pending.handOff}
                    />
                ) : null}
                <View style={styles.pillRow}>
                    <ActionPill onReassign={onReassign} onResolve={onResolve} onDismiss={onDismiss} />
                    <Pressable44
                        onPress={onChat}
                        accessibilityLabel="Chat"
                        pressedBackground={colors.inkHover}
                        style={[styles.chat, shadows.fab]}
                        haptic="selection"
                        testID="action-chat"
                    >
                        <ComposeIcon size={iconSizes.navigation} color={colors.onInk} />
                    </Pressable44>
                </View>
            </View>
        </KeyboardStickyView>
    )
}

const useStyles = createStyles(({ colors }) => ({
    bar: {
        backgroundColor: colors.background,
        paddingTop: 10,
        paddingHorizontal: layout.actionBarGutter,
        gap: 10,
        borderTopWidth: 1,
        borderTopColor: colors.footerHairline,
    },
    panel: {
        borderWidth: 1,
        borderColor: colors.hairline,
        borderRadius: radii.card,
        overflow: 'hidden',
        backgroundColor: colors.surface,
    },
    notice: { ...type.metaSmall, color: colors.orange, paddingHorizontal: 4 },
    pillRow: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 10,
    },
    // As tall as the action pill, so the two read as one row.
    chat: {
        width: 54,
        height: 54,
        borderRadius: radii.pill,
        backgroundColor: colors.ink,
        alignItems: 'center',
        justifyContent: 'center',
    },
}))
