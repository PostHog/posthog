import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import type { DefaultReviewModeEnumApi } from 'products/review_hog/frontend/generated/api.schemas'
import { reviewHogSettingsLogic } from 'products/review_hog/frontend/reviewHogSettingsLogic'

import { DEFAULT_REVIEW_MODE_OPTIONS } from './repositoryChoices'
import { reviewHogRepositoriesLogic } from './reviewHogRepositoriesLogic'
import { YouMark } from './YouMark'

export function MyDefaultCell({ className }: { className?: string }): JSX.Element {
    const { settings, settingsLoading } = useValues(reviewHogSettingsLogic)
    const { setMyDefault } = useActions(reviewHogRepositoriesLogic)
    const value = settings?.default_review_mode ?? 'follow'

    return (
        <div className={`flex min-w-0 flex-col gap-2 px-4 py-3 ${className ?? ''}`}>
            <div className="flex flex-col gap-0.5">
                <span className="text-sm font-semibold">My default</span>
                <span className="text-xs text-secondary">Every repository without your own choice follows this.</span>
            </div>
            <div className="flex items-center gap-1">
                <YouMark shown={value !== 'follow'} />
                <LemonSelect<DefaultReviewModeEnumApi>
                    size="small"
                    aria-label="My default"
                    value={value}
                    options={DEFAULT_REVIEW_MODE_OPTIONS}
                    onChange={(mode) => mode !== value && setMyDefault(mode)}
                    disabledReason={settings === null ? 'Loading…' : settingsLoading ? 'Saving…' : undefined}
                    data-attr="review-hog-default-review-mode"
                />
            </div>
        </div>
    )
}
