import { useValues } from 'kea'
import { useState } from 'react'

import { IconClockRewind } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { captureInboxReportAction } from '../../inboxAnalytics'
import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { ArtefactLogList } from './ArtefactLogList'
import { isInternalActivity, selectVisibleReportActivity } from './artefactTypes'
import { DetailSection } from './DetailSection'

/**
 * The report's chronological work-log: every artefact (judgments, findings, code references, diffs,
 * commits, task runs, notes, reviewers) rendered as a timeline entry. Reads the artefacts the detail
 * logic already loads (and polls while the report is active), so it stays in sync with the rest of
 * the detail view. Hidden entirely until at least one artefact is worth showing. Mirrors desktop
 * `ReportActivitySection`.
 */
export function ReportActivitySection({
    report,
    onToggleCollapsed,
}: {
    report: SignalReport
    onToggleCollapsed?: (collapsed: boolean) => void
}): JSX.Element | null {
    const { reportArtefacts, reportSignals, reportTasks } = useValues(
        inboxReportDetailLogic({ reportId: report.id, report })
    )
    const [showInternal, setShowInternal] = useState(false)

    // The badge counts what the log renders: `ArtefactLogList` hides internal retry records, so a
    // raw artefact count would promise entries the timeline never shows.
    const allArtefacts = selectVisibleReportActivity(reportArtefacts ?? [])
    if (allArtefacts.length === 0) {
        return null
    }
    const internalCount = allArtefacts.filter(isInternalActivity).length
    const artefacts = showInternal ? allArtefacts : allArtefacts.filter((artefact) => !isInternalActivity(artefact))
    const latest = allArtefacts.reduce((a, b) => (new Date(b.created_at) > new Date(a.created_at) ? b : a))

    // The logic already resolved the research/implementation tasks; hand them to the `task_run` rows
    // so they don't re-fetch the same tasks the Runs section just loaded.
    const knownTasks = new Map((reportTasks ?? []).map((entry) => [entry.task.id, entry.task]))
    const knownSignals = new Map((reportSignals ?? []).map((signal) => [signal.signal_id, signal]))

    return (
        <DetailSection
            icon={<IconClockRewind />}
            title="Activity"
            collapsible
            defaultCollapsed
            onToggleCollapsed={onToggleCollapsed}
            meta={
                <span className="flex items-center gap-1 text-xs text-tertiary tabular-nums">
                    <span>
                        {allArtefacts.length} {allArtefacts.length === 1 ? 'entry' : 'entries'} · last
                    </span>
                    <TZLabel time={latest.created_at} showPopover={false} />
                </span>
            }
        >
            {internalCount > 0 && (
                <LemonButton
                    type="tertiary"
                    size="xsmall"
                    className="mb-2 -ml-2"
                    onClick={() => {
                        captureInboxReportAction({
                            report,
                            actionType: showInternal ? 'collapse_section' : 'expand_section',
                            surface: 'detail_pane',
                            extra: { section: 'internal_activity' },
                        })
                        setShowInternal(!showInternal)
                    }}
                    data-attr="inbox-report-toggle-internal-activity"
                >
                    {showInternal ? 'Hide agent working notes' : `Show agent working notes (${internalCount})`}
                </LemonButton>
            )}
            <ArtefactLogList
                reportId={report.id}
                artefacts={artefacts}
                knownTasks={knownTasks}
                knownSignals={knownSignals}
                pullRequests={report.pull_requests}
                collapsedNoteCount={report.collapsed_note_count ?? 0}
            />
        </DetailSection>
    )
}
