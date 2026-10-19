import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'

import type { DefaultReviewModeEnumApi } from 'products/review_hog/frontend/generated/api.schemas'
import { reviewHogSettingsLogic } from 'products/review_hog/frontend/reviewHogSettingsLogic'

import { DEFAULT_REVIEW_MODE_OPTIONS, myDefaultNotice } from './repositoryChoices'
import { reviewHogRepositoriesLogic } from './reviewHogRepositoriesLogic'
import { withYouIcons } from './withYouIcons'
import { YouMark } from './YouMark'

export function MyDefaultCell({ className }: { className?: string }): JSX.Element {
    const { settings, settingsLoading } = useValues(reviewHogSettingsLogic)
    const { overview } = useValues(reviewHogRepositoriesLogic)
    const { setMyDefault } = useActions(reviewHogRepositoriesLogic)
    const { updateSettings } = useActions(reviewHogSettingsLogic)
    const value = settings?.default_review_mode ?? 'follow'
    const reviewDrafts = settings?.review_drafts ?? true
    const disabledReason = settings === null ? 'Loading…' : settingsLoading ? 'Saving…' : undefined
    const notice = myDefaultNotice(value, overview?.my_choices_unlike_default ?? null)

    return (
        <div className={`flex min-w-0 flex-col gap-2 px-4 py-3 ${className ?? ''}`}>
            <div className="flex flex-col gap-0.5">
                <span className="text-sm font-semibold">My default</span>
                <span className="text-xs text-secondary">For repositories where you have no saved choice.</span>
            </div>
            <div className="flex flex-wrap items-center gap-2">
                <LemonSelect<DefaultReviewModeEnumApi>
                    size="small"
                    aria-label="My default for automatic reviews"
                    value={value}
                    options={withYouIcons(DEFAULT_REVIEW_MODE_OPTIONS)}
                    onChange={(mode) => mode !== value && setMyDefault(mode)}
                    disabledReason={disabledReason}
                    data-attr="review-hog-default-review-mode"
                />
            </div>
            <div className="flex flex-col gap-0.5">
                <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs text-secondary">Review my draft pull requests</span>
                    <LemonSwitch
                        aria-label="Review my draft pull requests"
                        checked={reviewDrafts}
                        onChange={(checked) => updateSettings({ review_drafts: checked })}
                        disabledReason={disabledReason}
                        data-attr="review-hog-review-drafts"
                    />
                    <YouMark shown={!reviewDrafts} />
                </div>
                <span className="text-xs text-secondary">Turn off to wait until your PR is ready for review.</span>
            </div>
            {notice && (
                <LemonBanner type="info" className="text-xs">
                    {notice}
                </LemonBanner>
            )}
        </div>
    )
}
