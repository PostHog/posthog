import { LemonCard, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import type { SignalReportListApi } from 'products/signals/frontend/generated/api.schemas'
import { SignalReportPriorityBadge } from 'products/signals/frontend/inbox/components/badges/SignalReportPriorityBadge'
import { SignalReportStatusBadge } from 'products/signals/frontend/inbox/components/badges/SignalReportStatusBadge'
import type { SignalReportPriority, SignalReportStatus } from 'products/signals/frontend/inbox/types'
import { inboxReportDetailUrl } from 'products/signals/frontend/inbox/utils/inboxReportUrls'

export function SelfDrivingSuggestionRow({
    report,
    backUrl,
}: {
    report: SignalReportListApi
    backUrl: string
}): JSX.Element {
    // The inbox badges take the inbox's own status enum and priority union; the list endpoint carries the same values as strings.
    const status = report.status as unknown as SignalReportStatus
    const priority = report.priority as SignalReportPriority | null

    return (
        <LemonCard className="flex flex-col gap-2" hoverEffect={false}>
            <div className="flex flex-wrap items-center gap-2">
                <Link
                    to={inboxReportDetailUrl(report.id, backUrl)}
                    className="font-semibold"
                    data-attr="workflows-self-driving-suggestion"
                >
                    {report.title ?? 'Untitled suggestion'}
                </Link>
                <SignalReportPriorityBadge priority={priority} />
                <SignalReportStatusBadge status={status} />
                <span className="text-muted text-xs" translate="no">
                    <TZLabel time={report.updated_at} />
                </span>
            </div>
            {report.summary ? (
                <LemonMarkdown className="line-clamp-3 text-secondary" lowKeyHeadings disableImages>
                    {report.summary}
                </LemonMarkdown>
            ) : null}
        </LemonCard>
    )
}
