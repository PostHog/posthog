import { LemonModal, LemonButton } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import { Issue, IssueStatus } from '../types'
import { issueTrackerLogic } from '../IssueTrackerLogic'
import { STATUS_LABELS, STATUS_COLORS, ORIGIN_PRODUCT_LABELS, ORIGIN_PRODUCT_COLORS } from '../constants'

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
        <LemonModal isOpen={isOpen} onClose={onClose} title={`Issue #${issue.priority}`} width={600}>
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
                                ORIGIN_PRODUCT_COLORS[issue.originProduct]
                            }`}
                        >
                            {ORIGIN_PRODUCT_LABELS[issue.originProduct]}
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

                {/* Metadata */}
                <div className="grid grid-cols-2 gap-4 text-sm">
                    <div>
                        <span className="font-medium text-default">Created:</span>
                        <div className="text-muted">{formatDate(issue.createdAt)}</div>
                    </div>
                    <div>
                        <span className="font-medium text-default">Last Updated:</span>
                        <div className="text-muted">{formatDate(issue.updatedAt)}</div>
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
