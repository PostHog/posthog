import clsx from 'clsx'

import { LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { PRBrowserItemApi } from 'products/signals/frontend/generated/api.schemas'

export function PullRequestRow({
    pr,
    selected,
    onSelect,
}: {
    pr: PRBrowserItemApi
    selected: boolean
    onSelect: () => void
}): JSX.Element {
    return (
        <button
            type="button"
            aria-pressed={selected}
            onClick={onSelect}
            className={clsx(
                'w-full text-left p-4 border-b border-primary hover:bg-fill-highlight focus-visible:outline focus-visible:outline-accent min-w-0',
                selected && 'bg-fill-highlight border-l-2 border-l-accent'
            )}
        >
            <div className="text-xs text-secondary truncate mb-1">
                {pr.repository} #{pr.number}
            </div>
            <div className="font-semibold line-clamp-2 break-words mb-2">{pr.title}</div>
            <div className="flex flex-wrap items-center gap-2 text-xs text-secondary">
                <LemonTag size="small" type={pr.report ? 'primary' : 'default'}>
                    {pr.report ? 'Monitored' : 'Unmonitored'}
                </LemonTag>
                <span>
                    {pr.draft && pr.state === 'open'
                        ? 'Draft'
                        : pr.state === 'merged'
                          ? 'Merged'
                          : pr.state === 'closed'
                            ? 'Closed'
                            : 'Open'}
                </span>
                <TZLabel time={pr.created_at} />
            </div>
        </button>
    )
}
