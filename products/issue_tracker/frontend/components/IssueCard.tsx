import { LemonButton, LemonCard } from '@posthog/lemon-ui'
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
                <span className="text-xs text-muted ml-2">#{issue.priority}</span>
            </div>

            <p className="text-xs text-muted mb-3 line-clamp-2">{issue.description}</p>

            <div className="flex justify-between items-center">
                <span
                    className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium ${
                        ORIGIN_PRODUCT_COLORS[issue.originProduct]
                    }`}
                >
                    {ORIGIN_PRODUCT_LABELS[issue.originProduct]}
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
