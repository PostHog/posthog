import { BindLogic, useValues } from 'kea'

import { IconArrowRight, IconGithub } from '@posthog/icons'
import { LemonSkeleton, LemonTag, LemonTagType, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { ScenePanelLabel } from '~/layout/scenes/SceneLayout'

import type { ErrorTrackingLinkedReportApi } from '../../../../../signals/frontend/generated/api.schemas'
import { RelatedInboxReportsLogicProps, relatedInboxReportsLogic } from './relatedInboxReportsLogic'

// Mirrors the inbox's own status badge so a linked report reads the same on both sides
// of the integration, without the error tracking product reaching into inbox internals.
const STATUS_LABELS: Record<string, string> = {
    potential: 'Gathering',
    candidate: 'Queued',
    in_progress: 'Researching',
    pending_input: 'Needs input',
    ready: 'Ready',
    resolved: 'Resolved',
    failed: 'Failed',
}

const STATUS_TAG_TYPES: Record<string, LemonTagType> = {
    ready: 'success',
    resolved: 'completion',
    pending_input: 'caution',
    in_progress: 'warning',
    candidate: 'highlight',
    failed: 'danger',
    potential: 'default',
}

function statusLabel(status: string): string {
    return STATUS_LABELS[status] ?? status
}

function statusTagType(status: string): LemonTagType {
    return STATUS_TAG_TYPES[status] ?? 'muted'
}

function LinkedReportRow({ report }: { report: ErrorTrackingLinkedReportApi }): JSX.Element {
    return (
        <div className="flex flex-col gap-1 rounded border bg-surface-primary p-2">
            <Link to={urls.inboxReport('reports', report.id)} className="flex items-center gap-1 text-sm font-medium">
                <span className="flex-1 truncate">{report.title || 'Untitled report'}</span>
                <IconArrowRight className="size-3 shrink-0" />
            </Link>
            <div className="flex items-center gap-2">
                <LemonTag size="small" type={statusTagType(report.status)}>
                    {statusLabel(report.status)}
                </LemonTag>
                {report.implementation_pr_url && (
                    // Primary link is the inbox report above; the PR is a secondary indicator
                    // surfaced only when an agent has opened a fix.
                    <Link
                        to={report.implementation_pr_url}
                        target="_blank"
                        className="flex items-center gap-1 text-xs text-tertiary"
                    >
                        <IconGithub className="size-3" />
                        Fix in progress
                    </Link>
                )}
            </div>
        </div>
    )
}

function RelatedInboxReportsBody(): JSX.Element | null {
    const { relatedReports, relatedReportsLoading } = useValues(relatedInboxReportsLogic)

    if (relatedReportsLoading && relatedReports.length === 0) {
        return <LemonSkeleton className="h-12 w-full" />
    }

    // Quiet empty state: render nothing so an unlinked issue page stays uncluttered.
    if (relatedReports.length === 0) {
        return null
    }

    return (
        <ScenePanelLabel title="Inbox reports">
            <div className="flex flex-col gap-2">
                {relatedReports.map((report) => (
                    <LinkedReportRow key={report.id} report={report} />
                ))}
            </div>
        </ScenePanelLabel>
    )
}

/** ScenePanel section linking an error tracking issue to the inbox report(s) it grouped into. */
export function RelatedInboxReports({ issueId }: { issueId: string }): JSX.Element {
    const logicProps: RelatedInboxReportsLogicProps = { issueId }
    return (
        <BindLogic logic={relatedInboxReportsLogic} props={logicProps}>
            <RelatedInboxReportsBody />
        </BindLogic>
    )
}
