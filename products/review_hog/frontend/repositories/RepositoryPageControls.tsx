import { LemonButton } from '@posthog/lemon-ui'

import { PANE_LEFT, PANE_ROW } from './paneClasses'

export function RepositoryPageControls({
    first,
    last,
    total,
    page,
    pageCount,
    loading,
    onPageChange,
}: {
    first: number
    last: number
    total: number
    page: number
    pageCount: number
    loading: boolean
    onPageChange: (page: number) => void
}): JSX.Element {
    return (
        <div
            className={`col-span-full flex flex-wrap items-center justify-between gap-2 px-4 py-2.5 text-xs text-secondary ${PANE_LEFT} ${PANE_ROW}`}
        >
            <span>
                <span translate="no">
                    {first}-{last} of {total}
                </span>{' '}
                repositories
            </span>
            <span className="flex gap-1">
                <LemonButton
                    size="small"
                    type="secondary"
                    onClick={() => onPageChange(page - 1)}
                    disabledReason={page === 0 ? 'This is the first page' : loading ? 'Loading…' : undefined}
                >
                    Previous
                </LemonButton>
                <LemonButton
                    size="small"
                    type="secondary"
                    onClick={() => onPageChange(page + 1)}
                    disabledReason={page >= pageCount - 1 ? 'This is the last page' : loading ? 'Loading…' : undefined}
                >
                    Next
                </LemonButton>
            </span>
        </div>
    )
}
