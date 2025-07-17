import { useValues, useActions } from 'kea'
import { issueTrackerLogic } from '../IssueTrackerLogic'
import { IssueCard } from './IssueCard'
import { IssueModal } from './IssueModal'

export function BacklogView(): JSX.Element {
    const { backlogIssues, selectedIssue } = useValues(issueTrackerLogic)
    const { scopeIssue, openIssueModal, closeIssueModal } = useActions(issueTrackerLogic)

    return (
        <div className="space-y-4">
            <div className="flex justify-between items-center">
                <h2 className="text-xl font-semibold">Backlog</h2>
                <span className="text-sm text-muted">{backlogIssues.length} issues</span>
            </div>

            <div className="space-y-2">
                {backlogIssues.map((issue) => (
                    <IssueCard key={issue.id} issue={issue} onScope={scopeIssue} onClick={openIssueModal} />
                ))}
            </div>

            {backlogIssues.length === 0 && <div className="text-center py-8 text-muted">No issues in backlog</div>}

            <IssueModal issue={selectedIssue} isOpen={!!selectedIssue} onClose={closeIssueModal} />
        </div>
    )
}
