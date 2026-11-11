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
} from '@posthog/quill'

import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { QuillSuggestionsCaughtUp } from './QuillSuggestionsCaughtUp'
import { QuillSuggestionsReadsNote } from './QuillSuggestionsReadsNote'
import { SuggestionsReviewModalProps } from './SuggestionsReviewModal'
import { useFocusFollowsRemovedRow } from './useFocusFollowsRemovedRow'

export function QuillSuggestionsReviewModal({ title, summary, children }: SuggestionsReviewModalProps): JSX.Element {
    const { reviewOpen, stripState, listedSuggestions } = useValues(warehouseSuggestionsLogic)
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
                            {stripState === 'all_done' && <QuillSuggestionsCaughtUp placement="dialog" />}
                        </div>
                    </DialogBody>
                    <DialogFooter className="flex-wrap items-center justify-between gap-2">
                        <QuillSuggestionsReadsNote />
                        <DialogClose render={<Button variant="outline" />}>Close</DialogClose>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </>
    )
}
