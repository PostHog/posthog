import { IconPullRequest } from '@posthog/icons'

import { INBOX_FLAT_TAB_LIST_PARAMS } from '../../logics/reportListLogic'
import { ReportCard } from '../cards/ReportCard'
import { InboxReportList } from '../InboxReportList'
import { SelfDrivingInstallingHint } from '../SelfDrivingInstallingHint'

export function PullRequestsTab(): JSX.Element {
    return (
        <InboxReportList
            tabKey="pulls"
            listParams={INBOX_FLAT_TAB_LIST_PARAMS.pulls}
            Card={ReportCard}
            emptyState={{
                icon: <IconPullRequest className="text-2xl" />,
                title: 'No pull requests right now',
                description:
                    'When an agent ships a code change, the PR draft lands here for you to review and publish.',
                extra: (
                    <SelfDrivingInstallingHint>
                        Pull requests will be opened as soon as live data comes in.
                    </SelfDrivingInstallingHint>
                ),
            }}
        />
    )
}
