import { useActions, useValues } from 'kea'

import { LemonSelect, LemonSwitch } from '@posthog/lemon-ui'

import type { UrgencyThresholdEnumApi } from 'products/review_hog/frontend/generated/api.schemas'
import { reviewHogProjectSettingsLogic } from 'products/review_hog/frontend/repositories/reviewHogProjectSettingsLogic'
import { YouMark } from 'products/review_hog/frontend/repositories/YouMark'
import { reviewHogSettingsLogic } from 'products/review_hog/frontend/reviewHogSettingsLogic'

import { SettingRow } from './SettingRow'
import { SettingsTable } from './SettingsTable'

const THRESHOLD_OPTIONS: { value: UrgencyThresholdEnumApi; label: string }[] = [
    { value: 'consider', label: 'All findings' },
    { value: 'should_fix', label: 'Should fix and above' },
    { value: 'must_fix', label: 'Must fix only' },
]

type OnOff = 'on' | 'off'

function toOnOff(value: boolean): OnOff {
    return value ? 'on' : 'off'
}

const ON_OFF_OPTIONS: { value: OnOff; label: string }[] = [
    { value: 'on', label: 'On' },
    { value: 'off', label: 'Off' },
]

/**
 * "Mine" offers the project value as a follow option plus every other value. The project value
 * shows twice only while an own value equals it: one saved before the project value changed.
 * Picking "Same as project" then clears it.
 */
function mineOptions<T extends string>(
    options: { value: T; label: string }[],
    projectValue: T,
    ownValue: T | undefined
): { value: T | 'project'; label: string }[] {
    const projectLabel = options.find((option) => option.value === projectValue)?.label ?? projectValue
    return [
        { value: 'project', label: `Same as project (${projectLabel})` },
        ...options.filter((option) => option.value !== projectValue || option.value === ownValue),
    ]
}

/** The Deep review settings with a project value: Resolve, the threshold, and the celebration. */
export function FullReviewSettingsSection(): JSX.Element {
    const { settings, settingsLoading } = useValues(reviewHogSettingsLogic)
    const { updateSettings, followProjectDefault } = useActions(reviewHogSettingsLogic)
    const { projectSettings, editDisabledReason } = useValues(reviewHogProjectSettingsLogic)
    const { updateProjectSettings } = useActions(reviewHogProjectSettingsLogic)

    const mineDisabledReason = settings === null ? 'Loading…' : settingsLoading ? 'Saving…' : undefined
    // The project settings answer first after an admin edit; the personal settings reload after it.
    const projectThreshold =
        projectSettings?.urgency_threshold ?? settings?.project_defaults.urgency_threshold ?? 'consider'
    const projectCelebrate = toOnOff(
        projectSettings?.celebrate_clean_reviews ?? settings?.project_defaults.celebrate_clean_reviews ?? true
    )
    const ownThreshold = settings?.sources.urgency_threshold === 'user' ? settings.urgency_threshold : undefined
    const ownCelebrate =
        settings?.sources.celebrate_clean_reviews === 'user'
            ? toOnOff(settings.celebrate_clean_reviews ?? false)
            : undefined

    return (
        <SettingsTable>
            <SettingRow
                title="Resolve comments on my pull requests"
                description="Applies on your PRs. After a Deep review, ReviewHog pushes fix commits to your branch. Only your own opt-in counts, whoever starts the review. Never commits while the pull request is in the merge queue or has another pull request stacked on it. Without a PostHog account behind a PR, nothing is pushed."
                project={<span className="text-xs text-secondary">Personal only. Default: off</span>}
                mine={
                    <>
                        <YouMark shown={settings?.resolve_comments ?? false} />
                        <LemonSwitch
                            aria-label="Resolve comments on my pull requests"
                            checked={settings?.resolve_comments ?? false}
                            onChange={(checked) => updateSettings({ resolve_comments: checked })}
                            disabledReason={mineDisabledReason}
                            data-attr="review-hog-resolve-comments"
                        />
                    </>
                }
            />
            <SettingRow
                title="Post findings at or above"
                description="Applies to Deep reviews you start. Findings below this stay in the review report in PostHog."
                project={
                    <LemonSelect<UrgencyThresholdEnumApi>
                        size="small"
                        aria-label="Project: Post findings at or above"
                        value={projectThreshold}
                        options={THRESHOLD_OPTIONS}
                        onChange={(value) => updateProjectSettings({ urgency_threshold: value })}
                        disabledReason={editDisabledReason}
                        data-attr="review-hog-project-urgency-threshold"
                    />
                }
                mine={
                    <>
                        <YouMark shown={ownThreshold !== undefined} />
                        <LemonSelect<UrgencyThresholdEnumApi | 'project'>
                            size="small"
                            aria-label="Mine: Post findings at or above"
                            value={ownThreshold ?? 'project'}
                            options={mineOptions(THRESHOLD_OPTIONS, projectThreshold, ownThreshold)}
                            onChange={(value) =>
                                value === 'project'
                                    ? followProjectDefault('urgency_threshold')
                                    : updateSettings({ urgency_threshold: value })
                            }
                            disabledReason={mineDisabledReason}
                            data-attr="review-hog-urgency-threshold"
                        />
                    </>
                }
            />
            <SettingRow
                title="Celebrate clean reviews"
                description="Applies to Deep reviews you start. A clean Deep review gets a small celebration in the status comment."
                project={
                    <LemonSelect<OnOff>
                        size="small"
                        aria-label="Project: Celebrate clean reviews"
                        value={projectCelebrate}
                        options={ON_OFF_OPTIONS}
                        onChange={(value) => updateProjectSettings({ celebrate_clean_reviews: value === 'on' })}
                        disabledReason={editDisabledReason}
                        data-attr="review-hog-project-celebrate-clean-reviews"
                    />
                }
                mine={
                    <>
                        <YouMark shown={ownCelebrate !== undefined} />
                        <LemonSelect<OnOff | 'project'>
                            size="small"
                            aria-label="Mine: Celebrate clean reviews"
                            value={ownCelebrate ?? 'project'}
                            options={mineOptions(ON_OFF_OPTIONS, projectCelebrate, ownCelebrate)}
                            onChange={(value) =>
                                value === 'project'
                                    ? followProjectDefault('celebrate_clean_reviews')
                                    : updateSettings({ celebrate_clean_reviews: value === 'on' })
                            }
                            disabledReason={mineDisabledReason}
                            data-attr="review-hog-celebrate-clean-reviews"
                        />
                    </>
                }
            />
        </SettingsTable>
    )
}
