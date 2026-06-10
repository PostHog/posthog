import { JSX, MouseEvent } from 'react'

import { IconPullRequest } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'

export interface PrBadgeProps {
    prUrl: string | undefined
    /** Show a spinner instead of the PR icon while PR info is being refreshed */
    isPending?: boolean
    /** Small inline pill (for list rows) instead of a full LemonButton */
    compact?: boolean
}

function parsePrNumber(prUrl: string): string | null {
    return /\/pull\/(\d+)/.exec(prUrl)?.[1] ?? null
}

/**
 * "View PR" link badge for a task run's pull request.
 *
 * Ported from PostHog Code's `PRBadgeLink`, minus the state-driven coloring
 * (open/draft/closed/merged) — the web API only exposes `output.pr_url`, so
 * state colors need backend output enrichment first.
 */
export function PrBadge({ prUrl, isPending = false, compact = false }: PrBadgeProps): JSX.Element | null {
    if (!prUrl) {
        return null
    }

    const prNumber = parsePrNumber(prUrl)
    const label = prNumber ? `View PR #${prNumber}` : 'View PR'
    const handleClick = (event: MouseEvent): void => {
        event.stopPropagation()
    }

    if (compact) {
        return (
            <Link
                to={prUrl}
                target="_blank"
                targetBlankIcon={false}
                onClick={handleClick}
                className="inline-flex items-center gap-0.5 rounded px-1 py-0.5 text-[10px] bg-surface-secondary text-secondary hover:bg-surface-tertiary"
            >
                {isPending ? <Spinner className="text-[10px]" /> : <IconPullRequest className="shrink-0" />}
                <span>{label}</span>
            </Link>
        )
    }

    return (
        <LemonButton
            type="secondary"
            size="small"
            icon={isPending ? <Spinner /> : <IconPullRequest />}
            to={prUrl}
            targetBlank
            onClick={handleClick}
        >
            {label}
        </LemonButton>
    )
}
