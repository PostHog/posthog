import { TZLabel } from 'lib/components/TZLabel'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import type { SignalReportListApi } from 'products/signals/frontend/generated/api.schemas'

export function DashboardScoutReportEntry({ report }: { report: SignalReportListApi }): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                <Link
                    to={urls.inboxReport('reports', report.id)}
                    className="font-medium"
                    data-attr="dashboard-scout-report-link"
                >
                    {report.title || 'Untitled report'}
                </Link>
                <span className="text-xs text-secondary">
                    <TZLabel time={report.updated_at} />
                </span>
            </div>
            {report.summary_lead ? <p className="text-sm text-secondary mb-0">{report.summary_lead}</p> : null}
        </div>
    )
}
