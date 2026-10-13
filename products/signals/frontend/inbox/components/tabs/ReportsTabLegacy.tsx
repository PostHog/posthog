import { IconNotebook } from '@posthog/icons'

import { ReportCard } from '../cards/ReportCard'
import { InboxReportList } from '../InboxReportList'
import { SelfDrivingInstallingHint } from '../SelfDrivingInstallingHint'

export function ReportsTabLegacy(): JSX.Element {
    return (
        <InboxReportList
            tabKey="reports"
            Card={ReportCard}
            emptyState={{
                icon: <IconNotebook className="text-2xl" />,
                title: 'No reports yet',
                description:
                    "Reports are what agents surface when there's something worth your judgment but no clean code change to draft.",
                extra: (
                    <SelfDrivingInstallingHint>
                        Reports will start arriving as soon as live data comes in.
                    </SelfDrivingInstallingHint>
                ),
            }}
        />
    )
}
