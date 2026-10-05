import { ReactNode } from 'react'

import { LemonButton, LemonTag, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

export interface IssueRecommendationRowProps {
    id: string
    name: string
    status: ErrorTrackingIssue['status']
    /** The line under the issue name, e.g. how old it is and how often it fires. */
    subtitle: ReactNode
    /** Label of the button shown on hover while the issue is still active. */
    actionLabel: string
    /** Set for a destructive action, so the button reads as one. */
    actionIsDanger?: boolean
    onAction: () => void
    onUndo: () => void
}

/** One issue in a recommendation card. Hovering reveals the action; once the action lands,
 * the row dims and offers an undo. */
export function IssueRecommendationRow({
    id,
    name,
    status,
    subtitle,
    actionLabel,
    actionIsDanger,
    onAction,
    onUndo,
}: IssueRecommendationRowProps): JSX.Element {
    const isActive = status === 'active'

    return (
        <div className="border-b last:border-b-0">
            <Link
                subtle
                to={urls.errorTrackingIssue(id)}
                className={`group flex items-center gap-3 py-2 no-underline ${isActive ? '' : 'opacity-60'}`}
            >
                <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${isActive ? 'bg-warning' : 'bg-muted'}`} />
                <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium truncate flex items-center gap-2">
                        <span className="truncate">{name}</span>
                        {!isActive && (
                            <LemonTag size="small" type="muted">
                                {status}
                            </LemonTag>
                        )}
                    </div>
                    <div className="text-xs text-secondary">{subtitle}</div>
                </div>
                <div className="opacity-0 group-hover:opacity-100 transition-opacity">
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        status={isActive && actionIsDanger ? 'danger' : 'default'}
                        onClick={(e) => {
                            e.preventDefault()
                            e.stopPropagation()
                            isActive ? onAction() : onUndo()
                        }}
                    >
                        {isActive ? actionLabel : 'Undo'}
                    </LemonButton>
                </div>
            </Link>
        </div>
    )
}
