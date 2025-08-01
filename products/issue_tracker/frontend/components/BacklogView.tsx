import { useValues, useActions } from 'kea'
import { LemonButton } from '@posthog/lemon-ui'
import { issueTrackerLogic } from '../IssueTrackerLogic'
import { IssueCard } from './IssueCard'
import { IssueModal } from './IssueModal'
import { IssueCreateModal } from './IssueCreateModal'
import { userLogic } from 'scenes/userLogic'

export function BacklogView(): JSX.Element {
    const { backlogIssues, selectedIssue, isCreateModalOpen } = useValues(issueTrackerLogic)
    const { scopeIssue, openIssueModal, closeIssueModal, openCreateModal, closeCreateModal } = useActions(issueTrackerLogic)
    const { user } = useValues(userLogic)

    return (
        <div className="space-y-4">
            <div className="flex justify-between items-center">
                <h2 className="text-xl font-semibold">Backlog</h2>
                <div className="flex items-center gap-3">
                    <span className="text-sm text-muted">{backlogIssues.length} issues</span>
                    <LemonButton type="primary" onClick={openCreateModal}>
                        Create Issue
                    </LemonButton>
                </div>
            </div>

            <div className="space-y-2">
                {backlogIssues.map((issue) => (
                    <IssueCard key={issue.id} issue={issue} onScope={scopeIssue} onClick={openIssueModal} />
                ))}
            </div>

            {backlogIssues.length === 0 && <div className="text-center py-8 text-muted">No issues in backlog</div>}

            <IssueModal issue={selectedIssue} isOpen={!!selectedIssue} onClose={closeIssueModal} />
            <IssueCreateModal 
                isOpen={isCreateModalOpen} 
                onClose={closeCreateModal} 
                teamId={user?.team?.id || 0} 
            />
        </div>
    )
}
