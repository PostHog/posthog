import { useRouter } from 'expo-router'
import { type ReactElement, useEffect, useState } from 'react'
import { Linking } from 'react-native'
import { track } from '@/lib/analytics'
import { safeHttpsUrl } from '@/lib/urls'
import { useAsyncAction } from '@/lib/useAsyncAction'
import type { InboxItem, SnoozeChoice } from '@/model/types'
import { motion } from '@/ui/tokens'

import { actionBarStateFor } from '../handoff/actionBarState'
import { openExternalHandoff } from '../handoff/externalHandoff'
import { handoffAgentName, useHandoffPreferenceStore } from '../handoff/handoffPreferenceStore'
import { useHandoffStore } from '../handoff/handoffStore'
import { useHandoffEntry } from '../handoff/hooks'
import { mergeLiveRun } from '../handoff/liveReport'
import { useReport, useReportActions } from '../report/hooks'
import { AssigneeSheet } from '../reviewers/AssigneeSheet'
import { useGithubOnlyReviewerCount, useReportReviewers } from '../reviewers/hooks'
import { SnoozeSheet } from '../snooze/SnoozeSheet'
import type { RowAnchor } from './contextMenuPlacement'
import { ReportContextMenu } from './ReportContextMenu'

export interface RowMenuTarget {
    item: InboxItem
    anchor: RowAnchor
}

type RowMenuAction = 'reassign' | 'snooze' | 'chat' | 'mark_read' | 'hand_off' | 'view_pr'

type Step = 'menu' | 'assignee' | 'snooze'

type Overlay = Step | 'none'

const EXIT_MS = Math.max(motion.menu, motion.sheet)

interface InboxRowActionsProps {
    /** The row whose menu is open, or null when the menu and its sheets are closed. */
    target: RowMenuTarget | null
    onClose: () => void
}

export function InboxRowActions({ target, onClose }: InboxRowActionsProps): ReactElement | null {
    // Keeps the last target until the exit animation ends, then unmounts so its report queries stop observing.
    const [shown, setShown] = useState(target)
    if (target !== null && target !== shown) {
        setShown(target)
    }

    useEffect(() => {
        if (target) {
            return undefined
        }
        const timer = setTimeout(() => setShown(null), EXIT_MS)
        return () => clearTimeout(timer)
    }, [target])

    useEffect(() => {
        if (target) {
            track('mobile_inbox_report_menu_opened', { report_id: target.item.reportId })
        }
    }, [target])

    if (!shown) {
        return null
    }
    return (
        <RowActions
            key={shown.item.reportId}
            item={shown.item}
            anchor={shown.anchor}
            open={target !== null}
            onClose={onClose}
        />
    )
}

interface RowActionsProps {
    item: InboxItem
    anchor: RowAnchor
    open: boolean
    onClose: () => void
}

// Keyed by report id from the parent, so the report hooks mount for each selected report.
function RowActions({ item, anchor, open, onClose }: RowActionsProps): ReactElement {
    const router = useRouter()
    const { reportId } = item
    const reviewers = useReportReviewers(reportId)
    const githubOnlyReviewers = useGithubOnlyReviewerCount(reportId)
    const actions = useReportActions(reportId)
    const reportQuery = useReport(reportId)
    const entry = useHandoffEntry(reportId)
    const report = reportQuery.data ? mergeLiveRun(reportQuery.data, entry) : undefined
    const canHandOff = report !== undefined && actionBarStateFor(report).showHandoff
    // The list payload names the PR, so the menu offers it on its first frame instead of a handoff row that disappears once
    // the report loads. The loaded report still adds a PR a live run shipped after the list was fetched.
    const pullRequestUrl = item.pullRequestUrl ?? report?.work.pullRequest?.url
    const safePullRequestUrl = pullRequestUrl ? safeHttpsUrl(pullRequestUrl) : undefined
    const handoffTarget = useHandoffPreferenceStore((state) => state.target)
    const [handoffError, setHandoffError] = useState<string | undefined>()
    const [step, setStep] = useState<Step>('menu')
    const overlay: Overlay = open ? step : 'none'

    const close = (): void => {
        setStep('menu')
        onClose()
    }
    const choose = (action: RowMenuAction): void => {
        track('mobile_inbox_report_menu_action', { action, report_id: reportId })
    }
    const handOff = useAsyncAction(async () => {
        if (!report || !canHandOff || actions.pending.handOff) {
            return
        }
        choose('hand_off')
        setHandoffError(undefined)
        try {
            if (handoffTarget === 'posthog') {
                await actions.handOff()
                const notice = useHandoffStore.getState().reports[reportId]?.notice
                if (notice) {
                    setHandoffError(notice)
                    return
                }
            } else {
                await openExternalHandoff(handoffTarget, report)
            }
            close()
        } catch (error) {
            setHandoffError(error instanceof Error ? error.message : "Couldn't hand off this report. Try again.")
        }
    })
    const handoffPending = handOff.pending || actions.pending.handOff
    const viewPullRequest = (): void => {
        if (!safePullRequestUrl) {
            return
        }
        choose('view_pr')
        close()
        Linking.openURL(safePullRequestUrl).catch(() => undefined)
    }
    const reassign = (): void => {
        choose('reassign')
        setStep('assignee')
    }
    const openSnooze = (): void => {
        choose('snooze')
        setStep('snooze')
    }
    const chat = (): void => {
        choose('chat')
        close()
        router.push({ pathname: '/chat', params: { reportId } })
    }
    // The row turns read at once; a failed post reloads the read states, so the row shows unread again without a message.
    const markRead = (): void => {
        choose('mark_read')
        actions.markRead().catch(() => undefined)
        close()
    }
    const snooze = async (choice: SnoozeChoice): Promise<void> => {
        await actions.snooze(choice)
        close()
    }

    return (
        <>
            <ReportContextMenu
                visible={overlay === 'menu'}
                item={item}
                anchor={anchor}
                reassignDisabled={!reviewers}
                handoffLabel={`Hand off to ${handoffAgentName(handoffTarget)}`}
                showHandoff={!pullRequestUrl && (!report || canHandOff || handoffPending)}
                handoffDisabled={!canHandOff}
                showPullRequest={pullRequestUrl !== undefined}
                pullRequestDisabled={!safePullRequestUrl}
                onViewPullRequest={viewPullRequest}
                handoffPending={handoffPending}
                handoffError={handoffError}
                onHandOff={() => void handOff.run()}
                onClose={() => {
                    if (!handoffPending) {
                        close()
                    }
                }}
                onReassign={reassign}
                onSnooze={openSnooze}
                onChat={chat}
                onMarkRead={markRead}
            />
            <SnoozeSheet
                visible={overlay === 'snooze'}
                onClose={close}
                onSnooze={snooze}
                pending={actions.pending.snooze}
            />
            {reviewers ? (
                <AssigneeSheet
                    visible={overlay === 'assignee'}
                    current={reviewers}
                    githubOnlyCount={githubOnlyReviewers}
                    onClose={close}
                    onSave={actions.setReviewers}
                    pending={actions.pending.reviewers}
                />
            ) : null}
        </>
    )
}
