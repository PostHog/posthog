import { useRouter } from 'expo-router'
import { type ReactElement, useEffect, useState } from 'react'

import { track } from '@/lib/analytics'
import type { InboxItem, SnoozeChoice } from '@/model/types'
import { motion } from '@/ui/tokens'

import { useReportActions } from '../report/hooks'
import { AssigneeSheet } from '../reviewers/AssigneeSheet'
import { useGithubOnlyReviewerCount, useReportReviewers } from '../reviewers/hooks'
import { SnoozeSheet } from '../snooze/SnoozeSheet'
import type { RowAnchor } from './contextMenuPlacement'
import { ReportContextMenu } from './ReportContextMenu'

export interface RowMenuTarget {
    item: InboxItem
    anchor: RowAnchor
}

type RowMenuAction = 'reassign' | 'snooze' | 'chat' | 'mark_read'

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
    const [step, setStep] = useState<Step>('menu')
    const overlay: Overlay = open ? step : 'none'

    const close = (): void => {
        setStep('menu')
        onClose()
    }
    const choose = (action: RowMenuAction): void => {
        track('mobile_inbox_report_menu_action', { action, report_id: reportId })
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
                onClose={close}
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
