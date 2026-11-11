import { type ReactNode, useState } from 'react'

import { IconChevronDown, IconInfo, IconPeople } from '@posthog/icons'
import { LemonButton, Spinner, Tooltip } from '@posthog/lemon-ui'

import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'
import { ProfileBubbles } from 'lib/lemon-ui/ProfilePicture/ProfileBubbles'

import { EnrichedReviewer, ReviewerRemoval } from '../../types'
import { DetailSection } from './DetailSection'
import { getReviewerDisplayName } from './reviewerDisplay'
import { ReviewerClaim } from './SuggestedReviewerClaimControls'
import { SuggestedReviewersList } from './SuggestedReviewersList'

/** Avatars keep the section one line high near the top of the rail; the full list opens in a dropdown. */
export function SuggestedReviewersSectionView({
    reviewers,
    disabled,
    onRemove,
    addControl,
    claim,
    defaultOpen = false,
}: {
    reviewers: EnrichedReviewer[]
    disabled: boolean
    onRemove: (reviewers: EnrichedReviewer[], removal?: ReviewerRemoval) => void
    addControl: ReactNode
    claim?: ReviewerClaim
    defaultOpen?: boolean
}): JSX.Element {
    const [open, setOpen] = useState(defaultOpen)
    const people = reviewers.map((reviewer) => {
        const name = getReviewerDisplayName(reviewer)
        return { email: reviewer.user?.email ?? reviewer.github_login ?? name, name }
    })

    return (
        <DetailSection
            icon={<IconPeople />}
            title="Suggested reviewers"
            afterTitle={
                <Tooltip title="PostHog uses these suggestions to route the report. Add reviewers on the pull request to request a GitHub review.">
                    <span className="flex cursor-help items-center text-sm text-tertiary">
                        <IconInfo />
                    </span>
                </Tooltip>
            }
        >
            <div className="flex flex-wrap items-center justify-between gap-2">
                {reviewers.length === 0 ? (
                    <p className="m-0 text-xs text-tertiary">No suggested reviewers yet.</p>
                ) : (
                    <LemonDropdown
                        visible={open}
                        onClickOutside={() => setOpen(false)}
                        closeOnClickInside={false}
                        placement="bottom-start"
                        overlay={
                            <div className="w-[min(26rem,calc(100vw-2rem))] p-1">
                                <SuggestedReviewersList
                                    reviewers={reviewers}
                                    disabled={disabled}
                                    onRemove={onRemove}
                                    claim={claim}
                                />
                            </div>
                        }
                    >
                        <LemonButton
                            type="tertiary"
                            size="small"
                            onClick={() => setOpen((visible) => !visible)}
                            sideIcon={<IconChevronDown />}
                            aria-expanded={open}
                            className="-ml-2"
                            data-attr="inbox-report-suggested-reviewers-toggle"
                        >
                            <span className="flex items-center gap-2">
                                <ProfileBubbles people={people} limit={5} />
                                <span className="text-xs text-secondary">
                                    {reviewers.length} {reviewers.length === 1 ? 'reviewer' : 'reviewers'}
                                </span>
                            </span>
                        </LemonButton>
                    </LemonDropdown>
                )}
                <div className="flex items-center gap-2">
                    {disabled && <Spinner className="size-3" />}
                    {addControl}
                </div>
            </div>
        </DetailSection>
    )
}
