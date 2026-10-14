import type { ReactElement } from 'react'
import { StyleSheet, Text, View } from 'react-native'
import { KeyboardStickyView } from 'react-native-keyboard-controller'

import { POSTHOG_AGENT } from '@/model/agent'
import type { ActionBarState, ReportActions, ReportView, TaskRunView } from '@/model/types'
import { colors, layout, type } from '@/ui/tokens'
import { bottomOffset, useScreenInsets } from '@/ui/useScreenInsets'

import { ActionPill } from './ActionPill'
import { AgentStatusCard } from './AgentStatusCard'
import { DecisionCard } from './DecisionCard'
import { HandoffSplitButton } from './HandoffSplitButton'
import { isReplyPrompt } from './liveReport'
import { PrReadyCard } from './PrReadyCard'
import { type HandoffAnswer, runErrorMessage } from './types'

const DEFAULT_HANDED_META = 'A PR will land here to review'

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
}

function stoppedRun(task: TaskRunView | undefined): { title: string; meta: string } | undefined {
    if (task?.status === 'failed') {
        return {
            title: `${POSTHOG_AGENT.name} couldn't finish`,
            meta: runErrorMessage(task) ?? 'Hand off again to retry.',
        }
    }
    if (task?.status === 'cancelled') {
        return { title: 'The run was canceled', meta: 'Hand off again to start over.' }
    }
    return undefined
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
}: ActionBarProps): ReactElement {
    const insets = useScreenInsets()
    const pending = report.task?.pendingDecision
    const stopped = state === 'idle' ? stoppedRun(report.task) : undefined

    return (
        <KeyboardStickyView offset={{ opened: insets.bottom }}>
            <View style={[styles.bar, { paddingBottom: bottomOffset(insets, 38) }]} testID={`action-bar-${state}`}>
                {notice ? (
                    <Text style={styles.notice} accessibilityRole="alert" testID="handoff-notice">
                        {notice}
                    </Text>
                ) : null}
                {stopped ? (
                    <AgentStatusCard
                        mark={POSTHOG_AGENT.mark}
                        title={stopped.title}
                        meta={stopped.meta}
                        tone="stopped"
                        testID="agent-stopped-card"
                    />
                ) : null}
                {state === 'idle' ? (
                    <HandoffSplitButton
                        report={report}
                        onHandOff={() => void actions.handOff()}
                        onOpenPicker={onOpenHandoff}
                        pending={actions.pending.handOff}
                    />
                ) : null}
                {state === 'handed' ? (
                    <AgentStatusCard
                        mark={POSTHOG_AGENT.mark}
                        title={`${POSTHOG_AGENT.name} is on it`}
                        meta={report.task?.stage ?? DEFAULT_HANDED_META}
                        testID="agent-status-card"
                    />
                ) : null}
                {state === 'decision' && pending ? (
                    <DecisionCard
                        key={pending.id}
                        question={pending}
                        onAnswer={(input) => void actions.answerDecision(input)}
                        pending={actions.pending.answer}
                        {...(isReplyPrompt(pending) ? { eyebrow: 'WAITING FOR YOUR REPLY' } : {})}
                    />
                ) : null}
                {state === 'decided' && answer ? (
                    <AgentStatusCard
                        mark={POSTHOG_AGENT.mark}
                        title={answer.text}
                        meta={answer.meta ?? report.task?.stage}
                        {...(answer.canUndo ? { onUndo: () => void actions.undoDecision() } : {})}
                        testID="decided-card"
                    />
                ) : null}
                {state === 'pr_ready' && report.work.pullRequest ? (
                    <PrReadyCard pullRequest={report.work.pullRequest} />
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
    notice: {
        ...type.metaSmall,
        color: colors.orange,
        paddingHorizontal: 4,
    },
})
