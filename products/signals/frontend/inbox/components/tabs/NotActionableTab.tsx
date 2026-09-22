import { IconInfo } from '@posthog/icons'

import { ReportCard } from '../cards/ReportCard'
import { InboxReportList } from '../InboxReportList'

/**
 * Staff-only (internal) tab listing reports the agent judged `not_actionable`.
 * Same primitive as Pull requests / Reports – only the filter differs. Useful for
 * debugging signal quality.
 */
export function NotActionableTab(): JSX.Element {
    return (
        <InboxReportList
            tabKey="not-actionable"
            Card={ReportCard}
            emptyState={{
                icon: <IconInfo className="text-2xl" />,
                title: 'Nothing judged not-actionable',
                description:
                    'Reports the agent decided are not actionable land here, so the team can audit signal quality.',
            }}
        />
    )
}
