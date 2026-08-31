import { JSX } from 'react'

import { IconSearch } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

/** Which narrowing emptied the list, and so what the copy blames and the action undoes. */
export type InboxListNarrowing = 'filters' | 'for-you' | 'teammate'

const NARROWING_COPY: Record<InboxListNarrowing, { description: string; action: string; dataAttr: string }> = {
    filters: {
        description: 'Reports may still be waiting outside the filters you set.',
        action: 'Clear filters',
        dataAttr: 'inbox-empty-clear-filters',
    },
    'for-you': {
        description: 'Nothing here is suggested for you. Other people on the project may have reports waiting.',
        action: 'Show entire project',
        dataAttr: 'inbox-empty-show-entire-project',
    },
    teammate: {
        description: 'This teammate has nothing here. Other people on the project may have reports waiting.',
        action: 'Show entire project',
        dataAttr: 'inbox-empty-show-entire-project',
    },
}

/**
 * Shown when a narrowed report list matches nothing. A tab's own empty state claims the whole
 * project has nothing of that kind, which is wrong here and leaves no hint that a filter is what
 * emptied the list, so this state names the narrowing and offers the one action that undoes it.
 */
export function InboxNoMatchesEmptyState({
    narrowedBy,
    onClearFilters,
    onShowEntireProject,
}: {
    narrowedBy: InboxListNarrowing
    onClearFilters: () => void
    onShowEntireProject: () => void
}): JSX.Element {
    const copy = NARROWING_COPY[narrowedBy]

    return (
        <div className="mx-auto flex max-w-md flex-col items-center gap-2 py-12 text-center">
            <div className="mb-1 flex h-12 w-12 items-center justify-center rounded-full bg-fill-primary text-secondary">
                <IconSearch className="text-2xl" />
            </div>
            <h3 className="m-0 text-base font-semibold">No reports match this view</h3>
            <p className="m-0 text-sm text-tertiary">{copy.description}</p>
            <LemonButton
                type="secondary"
                size="small"
                className="mt-1"
                onClick={narrowedBy === 'filters' ? onClearFilters : onShowEntireProject}
                data-attr={copy.dataAttr}
            >
                {copy.action}
            </LemonButton>
        </div>
    )
}
