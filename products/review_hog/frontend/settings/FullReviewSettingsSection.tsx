import { useActions, useValues } from 'kea'

import { LemonButton, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'

import type { UrgencyThresholdEnumApi } from 'products/review_hog/frontend/generated/api.schemas'
import { reviewHogProjectSettingsLogic } from 'products/review_hog/frontend/repositories/reviewHogProjectSettingsLogic'
import { YouMark } from 'products/review_hog/frontend/repositories/YouMark'
import { reviewHogSettingsLogic } from 'products/review_hog/frontend/reviewHogSettingsLogic'

import { SettingRow } from './SettingRow'
import { SettingsTable } from './SettingsTable'

const THRESHOLD_OPTIONS: { value: UrgencyThresholdEnumApi; label: string }[] = [
    { value: 'consider', label: 'Consider (all)' },
    { value: 'should_fix', label: 'Should fix' },
    { value: 'must_fix', label: 'Must fix' },
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
 * Picking "(project)" then clears it.
 */
function mineOptions<T extends string>(
    options: { value: T; label: string }[],
    projectValue: T,
    ownValue: T | undefined
): { value: T | 'project'; label: string }[] {
    const projectLabel = options.find((option) => option.value === projectValue)?.label ?? projectValue
    return [
        { value: 'project', label: `${projectLabel} (project)` },
        ...options.filter((option) => option.value !== projectValue || option.value === ownValue),
    ]
}

export function FullReviewSettingsSection({ onEditSkills }: { onEditSkills: () => void }): JSX.Element {
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
        <SettingsTable
            title="Full review settings"
            description="Full reviews use these. Flash reads none of them. A review someone else starts on your PR uses their settings, but only your own Resolve choice can push to your branch."
        >
            <SettingRow
                title="Resolve comments on my pull requests"
                description="Applies on your PRs. After a Full review, ReviewHog pushes fix commits to your branch. Only your own opt-in counts, whoever starts the review. Never commits while the pull request is in the merge queue or has another pull request stacked on it. Without a PostHog account behind a PR, nothing is pushed."
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
                description="Applies to Full reviews you start. Lower findings stay in the report on the PostHog side."
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
                description="Applies to Full reviews you start. A clean Full review gets a small celebration in the status comment."
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
            <SettingRow
                title="Perspectives, blind spots, validation and resolution criteria"
                description="Applies to Full reviews you start. Resolution criteria also pick how fixes work: default, big gaps only, or small fixes only."
                project={<span className="text-xs text-secondary">Skills shared in this project</span>}
                mine={
                    <>
                        <YouMark shown={false} />
                        <LemonButton
                            size="small"
                            type="secondary"
                            onClick={onEditSkills}
                            data-attr="review-hog-edit-skills"
                        >
                            Edit my skills
                        </LemonButton>
                    </>
                }
            />
        </SettingsTable>
    )
}
