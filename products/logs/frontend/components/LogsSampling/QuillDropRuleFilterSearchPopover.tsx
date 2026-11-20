import { useRef } from 'react'

import { Popover, PopoverContent } from '@posthog/quill'

import { InfiniteSelectResults } from 'lib/components/TaxonomicFilter/InfiniteSelectResults'
import { TaxonomicFilterSearchInput } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterLogicProps } from 'lib/components/TaxonomicFilter/types'
import { isInsideOpenPopover } from 'lib/lemon-ui/Popover/Popover'

export function QuillDropRuleFilterSearchPopover({
    visible,
    taxonomicFilterLogicProps,
    searchInputRef,
    onShow,
    onClose,
}: {
    visible: boolean
    taxonomicFilterLogicProps: TaxonomicFilterLogicProps
    searchInputRef: React.MutableRefObject<HTMLInputElement | null>
    onShow: () => void
    onClose: () => void
}): JSX.Element {
    const anchorRef = useRef<HTMLDivElement | null>(null)
    const resultsRef = useRef<HTMLDivElement | null>(null)

    return (
        <Popover
            open={visible}
            onOpenChange={(next, details) => {
                if (next) {
                    return
                }

                // The results list portals its own Lemon popovers (property definitions) outside this popup.
                const landedOn =
                    details.reason === 'focus-out'
                        ? (details.event as FocusEvent).relatedTarget
                        : details.reason === 'outside-press'
                          ? details.event.target
                          : null
                if (
                    isInsideOpenPopover(landedOn) ||
                    (landedOn instanceof Node && anchorRef.current?.contains(landedOn))
                ) {
                    details.cancel()
                    return
                }

                onClose()
            }}
        >
            <div ref={anchorRef}>
                <TaxonomicFilterSearchInput
                    onClick={onShow}
                    searchInputRef={searchInputRef}
                    onClose={onClose}
                    onChange={onShow}
                />
            </div>
            <PopoverContent
                anchor={anchorRef}
                side="bottom"
                align="start"
                initialFocus={false}
                finalFocus={false}
                className="w-100 p-0"
            >
                {/* The results list is Lemon, so it keeps Lemon's colors inside the quill popover. */}
                <div data-not-quill ref={resultsRef}>
                    <InfiniteSelectResults
                        focusInput={() => searchInputRef.current?.focus()}
                        taxonomicFilterLogicProps={taxonomicFilterLogicProps}
                        popupAnchorElement={resultsRef.current}
                    />
                </div>
            </PopoverContent>
        </Popover>
    )
}
