import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSelect } from '@posthog/lemon-ui'

import type { DefaultReviewModeEnumApi } from 'products/review_hog/frontend/generated/api.schemas'
import { reviewHogSettingsLogic } from 'products/review_hog/frontend/reviewHogSettingsLogic'

import { DEFAULT_REVIEW_MODE_OPTIONS, myDefaultNotice } from './repositoryChoices'
import { reviewHogRepositoriesLogic } from './reviewHogRepositoriesLogic'
import { YouMark } from './YouMark'

export function MyDefaultCell({ className }: { className?: string }): JSX.Element {
    const { settings, settingsLoading } = useValues(reviewHogSettingsLogic)
    const { overview } = useValues(reviewHogRepositoriesLogic)
    const { setMyDefault } = useActions(reviewHogRepositoriesLogic)
    const value = settings?.default_review_mode ?? 'follow'
    const notice = myDefaultNotice(value, overview?.my_choices_unlike_default ?? null)

    return (
        <div className={`flex min-w-0 flex-col gap-2 px-4 py-3 ${className ?? ''}`}>
            <div className="flex flex-col gap-0.5">
                <span className="text-sm font-semibold">My default</span>
                <span className="text-xs text-secondary">
                    Applies to every repository where you have not picked something else.
                </span>
            </div>
            <div className="flex flex-wrap items-center gap-1">
                <YouMark shown={value !== 'follow'} />
                <span className="text-xs text-secondary">Automatic review on my PRs</span>
                <LemonSelect<DefaultReviewModeEnumApi>
                    size="small"
                    aria-label="Automatic review on my PRs"
                    value={value}
                    options={DEFAULT_REVIEW_MODE_OPTIONS}
                    onChange={(mode) => mode !== value && setMyDefault(mode)}
                    disabledReason={settings === null ? 'Loading…' : settingsLoading ? 'Saving…' : undefined}
                    data-attr="review-hog-default-review-mode"
                />
            </div>
            {notice && (
                <LemonBanner type="info" className="text-xs">
                    {notice}
                </LemonBanner>
            )}
        </div>
    )
}
