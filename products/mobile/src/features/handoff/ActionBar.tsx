import type { ReactElement } from 'react'
import { StyleSheet, Text, View } from 'react-native'
import { KeyboardStickyView } from 'react-native-keyboard-controller'

import type { ActionBarState, ReportActions, ReportView } from '@/model/types'
import { colors, layout, radii, type } from '@/ui/tokens'
import { bottomOffset, useScreenInsets } from '@/ui/useScreenInsets'

import { ActionPill } from './ActionPill'
import { AgentStatusCard } from './AgentStatusCard'
import { DecisionRequest } from './DecisionRequest'
import { HandoffSplitButton } from './HandoffSplitButton'
import { PullRequestCard } from './PullRequestCard'
import type { HandoffAnswer } from './types'

interface ActionBarProps {
    report: ReportView
    state: ActionBarState
    answer?: HandoffAnswer
    notice?: string
    actions: ReportActions
    onOpenHandoff: () => void
    onReassign: () => void
    onSnooze: () => void
    onChat: () => void
    onTaskChat?: () => void
}

export function ActionBar({
    report,
    state,
    answer,
    notice,
    actions,
    onOpenHandoff,
    onReassign,
    onSnooze,
    onChat,
    onTaskChat,
}: ActionBarProps): ReactElement {
    const insets = useScreenInsets()
    const hasPullRequests = state.pullRequests.length > 0
    const activity = state.activity
    const footerState = state.request
        ? 'decision'
        : hasPullRequests
          ? 'pr_ready'
          : state.answer
            ? 'decided'
            : state.showHandoff
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
                    onOpenChat={hasPullRequests ? undefined : onTaskChat}
                    testID={activity.tone === 'stopped' ? 'agent-stopped-card' : 'agent-status-card'}
                />
            ) : null}
            {state.answer ? (
                <AgentStatusCard
                    title={state.answer.text}
                    meta={state.answer.meta}
                    tone="idle"
                    onOpenChat={hasPullRequests ? undefined : onTaskChat}
                    {...(answer?.canUndo ? { onUndo: () => void actions.undoDecision() } : {})}
                    testID="decided-card"
                />
            ) : null}
            {state.request ? (
                <DecisionRequest
                    key={state.request.id}
                    question={state.request}
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
                    <PullRequestCard pullRequests={state.pullRequests} onTaskChat={onTaskChat} reportId={report.id}>
                        {activity || state.request || state.answer ? activityContent : null}
                    </PullRequestCard>
                ) : activity || state.request || state.answer ? (
                    <View style={styles.panel}>{activityContent}</View>
                ) : null}
                {state.showHandoff ? (
                    <HandoffSplitButton
                        report={report}
                        onHandOff={() => void actions.handOff()}
                        onOpenPicker={onOpenHandoff}
                        pending={actions.pending.handOff}
                    />
                ) : null}
                <ActionPill onReassign={onReassign} onSnooze={onSnooze} onChat={onChat} />
            </View>
        </KeyboardStickyView>
    )
}

const styles = StyleSheet.create({
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
        backgroundColor: colors.white,
    },
    notice: { ...type.metaSmall, color: colors.orange, paddingHorizontal: 4 },
})
