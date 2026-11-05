import type { ReactNode } from 'react'

import { IconInfo, IconPeople } from '@posthog/icons'
import { Popover, PopoverContent, PopoverTrigger, Spinner, Text } from '@posthog/quill'

import { EnrichedReviewer, ReviewerRemoval } from '../../types'
import { QuillDetailSection } from './QuillDetailSection'
import { QuillSuggestedReviewersList } from './QuillSuggestedReviewersList'
import { ReviewerClaim } from './suggestedReviewers'

/** The quill sibling of `SuggestedReviewersSectionView`, for the report page behind `today-rail-nav`. */
export function QuillSuggestedReviewersSectionView({
    reviewers,
    disabled,
    onRemove,
    addControl,
    claim,
}: {
    reviewers: EnrichedReviewer[]
    disabled: boolean
    onRemove: (reviewers: EnrichedReviewer[], removal?: ReviewerRemoval) => void
    addControl: ReactNode
    claim?: ReviewerClaim
}): JSX.Element {
    return (
        <QuillDetailSection
            icon={<IconPeople />}
            title="Suggested reviewers"
            collapsible
            afterTitle={
                // A popover rather than a tooltip, so a tap opens it too. The header is the collapse toggle,
                // so a click or key press on the icon must not collapse the section.
                <Popover>
                    <PopoverTrigger
                        openOnHover
                        nativeButton={false}
                        render={
                            <span
                                tabIndex={0}
                                className="flex cursor-help items-center text-subtle-foreground"
                                onClick={(e) => e.stopPropagation()}
                                onKeyDown={(e) => e.stopPropagation()}
                            />
                        }
                    >
                        <IconInfo />
                    </PopoverTrigger>
                    <PopoverContent side="top" className="max-w-72">
                        <Text size="xs" className="m-0">
                            PostHog uses these suggestions to route the report. Add reviewers on the pull request to
                            request a GitHub review.
                        </Text>
                    </PopoverContent>
                </Popover>
            }
        >
            <div className="flex flex-col gap-3">
                {reviewers.length === 0 ? (
                    <Text size="xs" variant="muted" className="m-0">
                        No suggested reviewers yet.
                    </Text>
                ) : (
                    <QuillSuggestedReviewersList
                        reviewers={reviewers}
                        disabled={disabled}
                        onRemove={onRemove}
                        claim={claim}
                    />
                )}
                <div className="flex flex-wrap items-center justify-end gap-2">
                    {disabled && <Spinner />}
                    {addControl}
                </div>
            </div>
        </QuillDetailSection>
    )
}
