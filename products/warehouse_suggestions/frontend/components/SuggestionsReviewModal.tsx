import { useActions, useValues } from 'kea'
import { ReactNode, useEffect, useRef } from 'react'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'

export interface SuggestionsReviewModalProps {
    title: string
    summary: ReactNode
    children: ReactNode
}

export function SuggestionsReviewModal({ title, summary, children }: SuggestionsReviewModalProps): JSX.Element {
    const { reviewOpen, status, stripState, listedSuggestions } = useValues(warehouseSuggestionsLogic)
    const { closeReview } = useActions(warehouseSuggestionsLogic)
    const bodyRef = useRef<HTMLDivElement>(null)
    const returnFocusRef = useRef<HTMLSpanElement>(null)
    useFocusFollowsRemovedRow(
        bodyRef,
        listedSuggestions.map((suggestion) => suggestion.id)
    )

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
                            <span>Based on read counts from the query log. PostHog never reads your query text.</span>
                            {status?.refreshed_at && (
                                <>
                                    <span> Refreshed </span>
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
                            className="px-3 py-6 text-center text-sm text-secondary"
                        >
                            All caught up. New suggestions appear as usage changes.
                        </div>
                    )}
                </div>
            </LemonModal>
        </>
    )
}

function useFocusFollowsRemovedRow(bodyRef: React.RefObject<HTMLDivElement>, rowIds: string[]): void {
    const previousRowIds = useRef(rowIds)

    useEffect(() => {
        const previous = previousRowIds.current
        previousRowIds.current = rowIds
        const removedIndex = previous.findIndex((id) => !rowIds.includes(id))
        const focusWasLost = !document.activeElement || document.activeElement === document.body
        if (removedIndex < 0 || !focusWasLost || !bodyRef.current) {
            return
        }
        const nextId = rowIds[removedIndex] ?? rowIds[removedIndex - 1]
        const target = nextId
            ? bodyRef.current.querySelector<HTMLElement>(
                  `[data-suggestion-row="${nextId}"] [data-suggestion-actions] button`
              )
            : bodyRef.current.querySelector<HTMLElement>('[data-suggestions-done]')
        target?.focus()
    }, [rowIds, bodyRef])
}
