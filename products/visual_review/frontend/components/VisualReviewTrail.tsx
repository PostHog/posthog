import { Fragment } from 'react'

import { Link } from '@posthog/lemon-ui'

export interface VisualReviewTrailCrumb {
    label: string
    to?: string
}

/** The in-page trail from the list tab to the entity on a detail page (Runs › branch). The title names the repository. */
export function VisualReviewTrail({ crumbs }: { crumbs: VisualReviewTrailCrumb[] }): JSX.Element {
    return (
        <div className="flex flex-wrap items-center gap-2 min-w-0">
            {crumbs.map((crumb, index) => (
                <Fragment key={crumb.label}>
                    {index > 0 && <span className="text-xs text-tertiary">›</span>}
                    {crumb.to ? (
                        <Link to={crumb.to} className="text-[13px] font-medium">
                            {crumb.label}
                        </Link>
                    ) : (
                        <span className="text-[13px] font-semibold break-all">{crumb.label}</span>
                    )}
                </Fragment>
            ))}
        </div>
    )
}
