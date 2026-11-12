import { useActions, useValues } from 'kea'
import { ReactNode, useEffect, useRef } from 'react'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { waitingSuggestionsText } from '../suggestionCopy'
import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { useFocusFollowsRemovedRow } from './useFocusFollowsRemovedRow'

export interface SuggestionsReviewModalProps {
    title: string
    summary: ReactNode
    children: ReactNode
}

export function SuggestionsReviewModal({ title, summary, children }: SuggestionsReviewModalProps): JSX.Element {
    const { reviewOpen, status, stripState, listedSuggestions, showingMore } = useValues(warehouseSuggestionsLogic)
    const { closeReview, showMore } = useActions(warehouseSuggestionsLogic)
    const bodyRef = useRef<HTMLDivElement>(null)
    const returnFocusRef = useRef<HTMLSpanElement>(null)
    const rowIds = listedSuggestions.map((suggestion) => suggestion.id)
    useFocusFollowsRemovedRow(bodyRef, rowIds, () =>
        bodyRef.current?.querySelector<HTMLElement>('[data-suggestions-done]')?.focus()
    )
    useFocusFirstRowOfANewBatch(bodyRef, rowIds)

    const focusSurfaceIfOpenerLeft = (): void => {
        if (document.activeElement === null || document.activeElement === document.body) {
            returnFocusRef.current?.focus()
        }
    }

    return (
        <>
            <span ref={returnFocusRef} tabIndex={-1} data-suggestions-return-focus className="sr-only" />
            <LemonModal
                isOpen={reviewOpen}
                onClose={closeReview}
                onAfterClose={focusSurfaceIfOpenerLeft}
                title={title}
                description={stripState === 'active' ? summary : undefined}
                width={820}
                footer={
                    <div className="flex w-full flex-wrap items-center justify-between gap-2">
                        <span className="min-w-0 flex-1 whitespace-normal text-xs text-muted">
                            <span>{`Based on the last ${status?.window_days ?? 0} days of reads. Cached dashboard views aren't counted.`}</span>
                            {status?.refreshed_at && (
                                <>
                                    <span> Updated </span>
                                    <TZLabel time={status.refreshed_at} showPopover={false} />
                                    <span>.</span>
                                </>
                            )}
                        </span>
                        <LemonButton type="secondary" onClick={closeReview}>
                            Close
                        </LemonButton>
                    </div>
                }
            >
                <div ref={bodyRef} className="@container/suggestions -mx-2">
                    <div className="divide-y divide-primary">{children}</div>
                    {stripState === 'all_done' && (
                        <div
                            tabIndex={-1}
                            data-suggestions-done
                            className="flex flex-col items-center gap-2 px-3 py-6 text-center text-sm text-secondary"
                        >
                            {status?.can_show_more ? (
                                <>
                                    <span>{`All caught up for today. ${waitingSuggestionsText(status.waiting)}`}</span>
                                    <LemonButton
                                        type="secondary"
                                        loading={showingMore}
                                        onClick={() => showMore('dialog')}
                                        data-attr="warehouse-suggestions-show-more"
                                    >
                                        Show more
                                    </LemonButton>
                                </>
                            ) : (
                                <span>All caught up. New suggestions appear as usage changes.</span>
                            )}
                        </div>
                    )}
                </div>
            </LemonModal>
        </>
    )
}

function useFocusFirstRowOfANewBatch(bodyRef: React.RefObject<HTMLDivElement>, rowIds: string[]): void {
    const previousCount = useRef(rowIds.length)

    useEffect(() => {
        const hadNoRows = previousCount.current === 0
        previousCount.current = rowIds.length
        const focusWasLost = !document.activeElement || document.activeElement === document.body
        if (!hadNoRows || rowIds.length === 0 || !focusWasLost || !bodyRef.current) {
            return
        }
        bodyRef.current
            .querySelector<HTMLElement>(`[data-suggestion-row="${rowIds[0]}"] [data-suggestion-actions] button`)
            ?.focus()
    }, [rowIds, bodyRef])
}
