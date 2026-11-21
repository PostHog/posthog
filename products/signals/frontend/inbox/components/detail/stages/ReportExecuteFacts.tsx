import { ReactNode } from 'react'

import { IconPeople, IconTerminal } from '@posthog/icons'
import { AvatarGroup, Text } from '@posthog/quill'

import { QuillPersonAvatar } from 'lib/components/QuillPersonAvatar/QuillPersonAvatar'
import { TZLabel } from 'lib/components/TZLabel'

import { EnrichedReviewer, SignalReport, SignalReportArtefact } from '../../../types'
import { deriveTaskPurpose, TaskRunArtefactContent } from '../artefactTypes'

function FactRow({ icon, name, children }: { icon: JSX.Element; name: string; children: ReactNode }): JSX.Element {
    return (
        <div className="grid grid-cols-[1rem_minmax(0,1fr)] items-center gap-x-2 gap-y-0.5 py-1.5 @md:grid-cols-[1rem_8rem_minmax(0,1fr)]">
            <span className="flex text-muted-foreground [&_svg]:size-3.5" aria-hidden>
                {icon}
            </span>
            <Text size="sm" weight="medium" render={<dt className="m-0" />}>
                {name}
            </Text>
            <Text
                size="sm"
                variant="muted"
                render={<dd className="m-0" />}
                className="col-start-2 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 @md:col-start-3"
            >
                {children}
            </Text>
        </div>
    )
}

function reviewersOf(artefacts: SignalReportArtefact[]): EnrichedReviewer[] {
    const latest = artefacts
        .filter((artefact) => artefact.type === 'suggested_reviewers')
        .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))[0]
    return Array.isArray(latest?.content) ? (latest.content as EnrichedReviewer[]) : []
}

function runsSummary(runs: SignalReportArtefact[]): string {
    const counts = new Map<string, number>()
    for (const run of runs) {
        const label = deriveTaskPurpose(run.content as TaskRunArtefactContent)?.purposeLabel.toLowerCase()
        if (label) {
            counts.set(label, (counts.get(label) ?? 0) + 1)
        }
    }
    const kinds = [...counts].map(([label, count]) => `${count} ${label}`).join(', ')
    return `${runs.length} ${runs.length === 1 ? 'run' : 'runs'}: ${kinds}`
}

export function ReportExecuteFacts({
    report,
    artefacts,
    isClaimedByMe,
}: {
    report: SignalReport
    artefacts: SignalReportArtefact[]
    isClaimedByMe: boolean
}): JSX.Element {
    const reviewers = reviewersOf(artefacts)
    const owner = report.assignee?.responsible_user ?? report.assignee?.user
    const suggested = reviewers.filter((reviewer) => reviewer.user && reviewer.user.uuid !== owner?.uuid)
    const runs = artefacts
        .filter((artefact) => artefact.type === 'task_run')
        .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))
    const claim = owner ? (isClaimedByMe ? 'You claimed this report' : `${owner.first_name} claimed this report`) : null
    const suggestion =
        suggested.length > 0
            ? `${suggested.length} suggested ${suggested.length === 1 ? 'reviewer' : 'reviewers'}`
            : null

    return (
        <dl className="m-0 flex flex-col" data-attr="inbox-report-execute-facts">
            <FactRow icon={<IconPeople />} name="Reviewers">
                <AvatarGroup size="xs">
                    {owner && <QuillPersonAvatar name={owner.first_name} email={owner.email} size="xs" />}
                    {suggested.map(
                        (reviewer) =>
                            reviewer.user && (
                                <QuillPersonAvatar
                                    key={reviewer.user.uuid}
                                    name={reviewer.user.first_name}
                                    email={reviewer.user.email}
                                    size="xs"
                                />
                            )
                    )}
                </AvatarGroup>
                <span>{[claim, suggestion].filter(Boolean).join(' · ') || 'No reviewers yet'}</span>
            </FactRow>
            {runs.length > 0 && (
                <FactRow icon={<IconTerminal />} name="Runs">
                    <span>{runsSummary(runs)}</span>
                    <span aria-hidden>·</span>
                    <span>Last started</span>
                    <TZLabel time={runs[0].created_at} />
                </FactRow>
            )}
        </dl>
    )
}
