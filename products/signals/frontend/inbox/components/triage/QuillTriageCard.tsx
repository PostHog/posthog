import './QuillInboxTriage.scss'

import { useActions, useValues } from 'kea'

import { Button, Kbd, Text } from '@posthog/quill'

import { TodayReportAbstract } from 'scenes/project-homepage/today/TodayReportAbstract'
import { todayReportLogic } from 'scenes/project-homepage/today/todayReportLogic'
import { TodayReportProposal } from 'scenes/project-homepage/today/TodayReportProposal'
import { TodayReportSignalRow } from 'scenes/project-homepage/today/TodayReportSignalRow'
import { TodayReportTitle } from 'scenes/project-homepage/today/TodayReportTitle'
import { userLogic } from 'scenes/userLogic'

import { inboxTriageLogic } from '../../logics/inboxTriageLogic'
import { SignalReport } from '../../types'
import { isReportClaimable } from '../../utils/reportClaim'
import { hasActiveReportPullRequest } from '../../utils/reportPullRequests'
import { QuillReportFacts } from '../detail/QuillReportFacts'
import { QuillReportSourceIcons } from '../detail/QuillReportSourceIcons'

const CLOSED_EVIDENCE_ROWS = 2

function Separator(): JSX.Element {
    return <span aria-hidden>·</span>
}

function KeyButton({
    label,
    shortcut,
    onClick,
    dataAttr,
    plain = false,
    disabledReason,
}: {
    label: string
    shortcut: string
    onClick: () => void
    dataAttr: string
    plain?: boolean
    disabledReason?: string | null
}): JSX.Element {
    return (
        <Button
            variant={plain ? 'default' : 'outline'}
            onClick={onClick}
            disabledReason={disabledReason ?? undefined}
            data-attr={dataAttr}
        >
            {label}
            <Kbd>{shortcut}</Kbd>
        </Button>
    )
}

/** The triage card: the top of the report page, a count line, and the first evidence. It has no primary button. */
export function QuillTriageCard({ report, expanded }: { report: SignalReport; expanded: boolean }): JSX.Element {
    const { user } = useValues(userLogic)
    const { canCreatePr, createPrDisabledReason, implementationDisabledReason } = useValues(inboxTriageLogic)
    const { claimCurrent, resolveCurrent, dismissCurrent, createPrForCurrent, toggleExpanded, openCurrent } =
        useActions(inboxTriageLogic)
    const { page, shownEvidence, evidenceCount } = useValues(todayReportLogic({ reportId: report.id }))
    const myUuid = user?.uuid ?? null
    const evidence = expanded ? shownEvidence : shownEvidence.slice(0, CLOSED_EVIDENCE_ROWS)

    return (
        <article className="QuillTriage__card" data-attr="inbox-triage-card">
            <div className="flex flex-col gap-5">
                <header className="flex flex-col gap-3">
                    <QuillReportFacts
                        report={report}
                        timestampField={report.created_at === report.updated_at ? 'created_at' : 'updated_at'}
                        className="flex min-h-7 flex-wrap items-center gap-x-1.5 gap-y-1"
                    >
                        <QuillReportSourceIcons report={report} className="QuillTriage__icons me-1" />
                    </QuillReportFacts>
                    <TodayReportTitle report={report} />
                </header>
                {page && <TodayReportAbstract report={report} />}
                <Text size="xs" variant="muted" render={<div />} className="flex flex-wrap items-center gap-x-1.5">
                    {page && (
                        <>
                            <span>{`${evidenceCount} evidence ${evidenceCount === 1 ? 'item' : 'items'}`}</span>
                            <Separator />
                        </>
                    )}
                    <span>{hasActiveReportPullRequest(report) ? 'Pull request open' : 'No pull request'}</span>
                    {report.is_suggested_reviewer && (
                        <>
                            <Separator />
                            <span>Suggested for you</span>
                        </>
                    )}
                </Text>
                {expanded && page && <TodayReportProposal reportId={report.id} />}
                {evidence.length > 0 && (
                    <div className="-mx-2 flex flex-col">
                        {evidence.map((signal) => (
                            <TodayReportSignalRow key={signal.signal_id} reportId={report.id} signal={signal} />
                        ))}
                    </div>
                )}
            </div>
            <footer className="QuillTriage__keys">
                {isReportClaimable(report, myUuid) && (
                    <KeyButton label="Claim" shortcut="U" onClick={claimCurrent} dataAttr="inbox-triage-claim" />
                )}
                <KeyButton label="Resolve" shortcut="R" onClick={resolveCurrent} dataAttr="inbox-triage-resolve" />
                <KeyButton label="Dismiss" shortcut="A" onClick={dismissCurrent} dataAttr="inbox-triage-dismiss" />
                {canCreatePr && (
                    <KeyButton
                        label="Create PR"
                        shortcut="C"
                        onClick={createPrForCurrent}
                        disabledReason={createPrDisabledReason ?? implementationDisabledReason}
                        dataAttr="inbox-triage-create-pr"
                    />
                )}
                <span className="flex-1" />
                <KeyButton
                    plain
                    label={expanded ? 'Read less' : 'Read more'}
                    shortcut="↵"
                    onClick={toggleExpanded}
                    dataAttr="inbox-triage-toggle-summary"
                />
                <KeyButton
                    plain
                    label="Open report"
                    shortcut="O"
                    onClick={openCurrent}
                    dataAttr="inbox-triage-open-report"
                />
            </footer>
        </article>
    )
}
