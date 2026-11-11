import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import {
    Button,
    Dialog,
    DialogBody,
    DialogClose,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Text,
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'

import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { SuggestionsReviewModalProps } from './SuggestionsReviewModal'
import { useFocusFollowsRemovedRow } from './useFocusFollowsRemovedRow'

export function QuillSuggestionsReviewModal({ title, summary, children }: SuggestionsReviewModalProps): JSX.Element {
    const { reviewOpen, status, stripState, listedSuggestions } = useValues(warehouseSuggestionsLogic)
    const { closeReview } = useActions(warehouseSuggestionsLogic)
    const bodyRef = useRef<HTMLDivElement>(null)
    const returnFocusRef = useRef<HTMLSpanElement>(null)
    useFocusFollowsRemovedRow(
        bodyRef,
        listedSuggestions.map((suggestion) => suggestion.id),
        () => bodyRef.current?.querySelector<HTMLElement>('[data-suggestions-done]')?.focus()
    )

    const focusSurfaceIfOpenerLeft = (open: boolean): void => {
        if (!open && (document.activeElement === null || document.activeElement === document.body)) {
            returnFocusRef.current?.focus()
        }
    }

    return (
        <>
            <span ref={returnFocusRef} tabIndex={-1} data-suggestions-return-focus className="sr-only" />
            <Dialog
                open={reviewOpen}
                onOpenChange={(open: boolean) => !open && closeReview()}
                onOpenChangeComplete={focusSurfaceIfOpenerLeft}
            >
                <DialogContent size="wide" className="max-w-205" data-attr="warehouse-suggestions-review-dialog">
                    <DialogHeader>
                        <DialogTitle>{title}</DialogTitle>
                        {stripState === 'active' && <DialogDescription>{summary}</DialogDescription>}
                    </DialogHeader>
                    <DialogBody viewportClassName="p-0">
                        <div ref={bodyRef} className="@container/suggestions">
                            <div className="divide-y divide-border">{children}</div>
                            {stripState === 'all_done' && (
                                <Text
                                    size="xs"
                                    variant="muted"
                                    tabIndex={-1}
                                    data-suggestions-done
                                    className="px-3 py-6 text-center"
                                >
                                    All caught up. New suggestions appear as usage changes.
                                </Text>
                            )}
                        </div>
                    </DialogBody>
                    <DialogFooter className="flex-wrap items-center justify-between gap-2">
                        <Text size="xs" variant="muted" render={<span />} className="min-w-0 flex-1">
                            <span>{`Based on the last ${status?.window_days ?? 0} days of reads. Cached dashboard views aren't counted.`}</span>
                            {status?.refreshed_at && (
                                <>
                                    <span> Updated </span>
                                    <TZLabel time={status.refreshed_at} showPopover={false} />
                                    <span>.</span>
                                </>
                            )}
                        </Text>
                        <DialogClose render={<Button variant="outline" />}>Close</DialogClose>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </>
    )
}
