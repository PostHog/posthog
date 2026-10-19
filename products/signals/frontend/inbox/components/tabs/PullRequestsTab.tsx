import { ReportCard } from '../cards/ReportCard'
import { InboxWaitingForWork } from '../emptyState/InboxWaitingForWork'
import { InboxReportList } from '../InboxReportList'

export function PullRequestsTab(): JSX.Element {
    return <InboxReportList tabKey="pulls" Card={ReportCard} emptyState={{ content: <InboxWaitingForWork /> }} />
}
