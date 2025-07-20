import { LemonButton, LemonCard } from '@posthog/lemon-ui'
import { IconGithub, IconBranch } from 'lib/lemon-ui/icons'
import { Issue, IssueStatus } from '../types'
import { ORIGIN_PRODUCT_LABELS, ORIGIN_PRODUCT_COLORS } from '../constants'

interface IssueCardProps {
    issue: Issue
    onScope?: (issueId: string) => void
    onClick?: (issueId: string) => void
    draggable?: boolean
}

export function IssueCard({ issue, onScope, onClick, draggable = false }: IssueCardProps): JSX.Element {
    const handleCardClick = (e: React.MouseEvent): void => {
        // Don't trigger click when dragging
        if (draggable && e.defaultPrevented) {
            return
        }
        if (onClick) {
            onClick(issue.id)
        }
    }

    return (
        <LemonCard
            className={`p-3 ${draggable ? 'cursor-move' : 'cursor-pointer'}`}
            hoverEffect={true}
            onClick={handleCardClick}
        >
            <div className="flex justify-between items-start mb-2">
                <h4 className="font-medium text-sm leading-tight">{issue.title}</h4>
            </div>

            <p className="text-xs text-muted mb-3 line-clamp-2">{issue.description}</p>

            {/* GitHub Integration Status */}
            {(issue.github_branch || issue.github_pr_url) && (
                <div className="flex items-center gap-1 mb-2">
                    <IconGithub className="text-xs" />
                    {issue.github_branch && (
                        <div className="flex items-center gap-1 text-xs text-muted">
                            <IconBranch />
                            <span className="truncate max-w-32">{issue.github_branch}</span>
                        </div>
                    )}
                    {issue.github_pr_url && (
                        <a
                            href={issue.github_pr_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="flex items-center gap-1 text-xs text-link hover:text-link-hover"
                            onClick={(e) => e.stopPropagation()}
                        >
                            <span>↗</span>
                            <span>PR</span>
                        </a>
                    )}
                </div>
            )}

            <div className="flex justify-between items-center">
                <span
                    className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium ${
                        ORIGIN_PRODUCT_COLORS[issue.origin_product]
                    }`}
                >
                    {ORIGIN_PRODUCT_LABELS[issue.origin_product]}
                </span>

                {issue.status === IssueStatus.BACKLOG && onScope && (
                    <LemonButton
                        size="xsmall"
                        type="primary"
                        onClick={(e) => {
                            e.stopPropagation()
                            onScope(issue.id)
                        }}
                    >
                        Scope
                    </LemonButton>
                )}
            </div>
        </LemonCard>
    )
}
