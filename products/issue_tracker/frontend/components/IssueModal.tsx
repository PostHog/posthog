import { LemonModal, LemonButton } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import { Issue, IssueStatus } from '../types'
import { issueTrackerLogic } from '../IssueTrackerLogic'
import { STATUS_LABELS, STATUS_COLORS, ORIGIN_PRODUCT_LABELS, ORIGIN_PRODUCT_COLORS } from '../constants'
import { IssueProgressDisplay } from './IssueProgressDisplay'

interface IssueModalProps {
    issue: Issue | null
    isOpen: boolean
    onClose: () => void
}

export function IssueModal({ issue, isOpen, onClose }: IssueModalProps): JSX.Element {
    const { scopeIssue } = useActions(issueTrackerLogic)

    if (!issue) {
        return <></>
    }

    const formatDate = (dateString: string): string => {
        return new Date(dateString).toLocaleDateString('en-US', {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
        })
    }

    const handleScope = (): void => {
        scopeIssue(issue.id)
        onClose()
    }

    return (
        <LemonModal isOpen={isOpen} onClose={onClose} title={issue.title} width={600}>
            <div className="space-y-6">
                {/* Header with status and origin */}
                <div className="flex justify-between items-start">
                    <div className="flex gap-2">
                        <span
                            className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium ${
                                STATUS_COLORS[issue.status]
                            }`}
                        >
                            {STATUS_LABELS[issue.status]}
                        </span>
                        <span
                            className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium ${
                                ORIGIN_PRODUCT_COLORS[issue.origin_product]
                            }`}
                        >
                            {ORIGIN_PRODUCT_LABELS[issue.origin_product]}
                        </span>
                    </div>
                    <span className="text-xs text-muted">Position: {issue.position}</span>
                </div>

                {/* Title */}
                <div>
                    <h2 className="text-xl font-semibold text-default mb-2">{issue.title}</h2>
                </div>

                {/* Description */}
                <div>
                    <h3 className="text-sm font-medium text-default mb-2">Description</h3>
                    <p className="text-sm text-muted leading-relaxed">{issue.description}</p>
                </div>

                {/* Repository Configuration */}
                {issue.repository_scope && (
                    <div>
                        <h3 className="text-sm font-medium text-default mb-2">Repository Configuration</h3>
                        <div className="bg-bg-light p-3 rounded border">
                            <div className="space-y-2">
                                <div className="flex items-center gap-2">
                                    <span className="text-xs font-medium text-muted">Scope:</span>
                                    <span className="text-sm capitalize">{issue.repository_scope.replace('_', ' ')}</span>
                                </div>
                                
                                {issue.repository_scope === 'single' && issue.primary_repository && (
                                    <div className="flex items-center gap-2">
                                        <span className="text-xs font-medium text-muted">Repository:</span>
                                        <span className="text-sm font-mono text-primary">
                                            {issue.primary_repository.organization}/{issue.primary_repository.repository}
                                        </span>
                                    </div>
                                )}
                                
                                {issue.repository_scope === 'multiple' && issue.repository_list && (
                                    <div>
                                        <span className="text-xs font-medium text-muted">Repositories ({issue.repository_list.length}):</span>
                                        <div className="mt-1 space-y-1">
                                            {issue.repository_list.map((repo, index) => (
                                                <div key={index} className="text-sm font-mono text-primary">
                                                    {repo.organization}/{repo.repository}
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}
                                
                                {issue.repository_scope === 'smart_select' && (
                                    <div className="flex items-center gap-2">
                                        <span className="text-xs font-medium text-muted">Mode:</span>
                                        <span className="text-sm">AI will select repositories based on issue context</span>
                                    </div>
                                )}
                            </div>
                        </div>
                    </div>
                )}

                {/* Progress Display - only show for in_progress, testing, or done issues */}
                {[IssueStatus.IN_PROGRESS, IssueStatus.TESTING, IssueStatus.DONE].includes(issue.status) && (
                    <IssueProgressDisplay issue={issue} />
                )}

                {/* Metadata */}
                <div className="grid grid-cols-2 gap-4 text-sm">
                    <div>
                        <span className="font-medium text-default">Created:</span>
                        <div className="text-muted">{formatDate(issue.created_at)}</div>
                    </div>
                    <div>
                        <span className="font-medium text-default">Last Updated:</span>
                        <div className="text-muted">{formatDate(issue.updated_at)}</div>
                    </div>
                </div>

                {/* Actions */}
                <div className="flex justify-between items-center pt-4 border-t border-border">
                    <div>
                        {issue.status === IssueStatus.BACKLOG && (
                            <LemonButton type="primary" onClick={handleScope}>
                                Scope to Todo
                            </LemonButton>
                        )}
                    </div>
                    <LemonButton onClick={onClose}>Close</LemonButton>
                </div>
            </div>
        </LemonModal>
    )
}
