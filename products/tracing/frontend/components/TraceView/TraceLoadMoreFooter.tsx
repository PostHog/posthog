import { LemonButton, Spinner } from '@posthog/lemon-ui'

export interface TraceLoadMoreFooterProps {
    /** A next page of spans is being fetched. */
    loadingMore: boolean
    onLoadMore?: () => void
}

/** Render it only while the open trace has more spans than the loaded pages. */
export function TraceLoadMoreFooter({ loadingMore, onLoadMore }: TraceLoadMoreFooterProps): JSX.Element {
    return (
        <div className="flex items-center justify-center gap-2 py-2 text-xs text-muted border-t">
            {loadingMore ? (
                <>
                    <Spinner />
                    <span>Loading more spans…</span>
                </>
            ) : (
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    onClick={() => onLoadMore?.()}
                    // pinned: autocapture selects on this value, so renaming it breaks saved actions
                    data-attr="trace-view-load-more-spans"
                >
                    Load more spans
                </LemonButton>
            )}
        </div>
    )
}
