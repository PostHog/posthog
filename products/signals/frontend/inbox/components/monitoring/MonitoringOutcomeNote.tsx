import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { ReportMonitoringOutcomeApi } from 'products/signals/frontend/generated/api.schemas'

import { inboxReportDetailUrl } from '../../utils/inboxReportUrls'
import { MonitoringTime } from './MonitoringTime'

const OUTCOME_HEADING: Record<ReportMonitoringOutcomeApi['kind'], string> = {
    resolved: 'Resolved: every check passed',
    resolved_by_assessment: 'Resolved: an agent confirmed the fix from other evidence',
    resolved_manually: 'Resolved by a person',
    closed: 'Closed: the fix was not shown to work',
}

export function MonitoringOutcomeNote({ outcome }: { outcome: ReportMonitoringOutcomeApi }): JSX.Element {
    const followUp = outcome.follow_up
    return (
        <div className="flex flex-col gap-1 rounded bg-surface-secondary p-3 text-sm">
            <div className="font-semibold">{OUTCOME_HEADING[outcome.kind]}</div>
            <div className="text-secondary">
                Monitoring ended <MonitoringTime iso={outcome.ended_at} />.
            </div>
            {followUp ? (
                <div>
                    Follow-up report:{' '}
                    <Link to={inboxReportDetailUrl(followUp.report_id, urls.inbox('monitoring'))}>
                        {followUp.title ?? 'Untitled report'}
                    </Link>
                </div>
            ) : outcome.kind === 'closed' ? (
                <div className="text-secondary">Follow-up research has been requested.</div>
            ) : null}
        </div>
    )
}
