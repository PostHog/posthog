import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'

import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import type {
    DefaultReviewModeEnumApi,
    UrgencyThresholdEnumApi,
} from 'products/review_hog/frontend/generated/api.schemas'
import {
    DEFAULT_REVIEW_MODE_OPTIONS,
    myDefaultNotice,
} from 'products/review_hog/frontend/repositories/repositoryChoices'
import { RepositoryList } from 'products/review_hog/frontend/repositories/RepositoryList'
import { RepositoryMyRow } from 'products/review_hog/frontend/repositories/RepositoryMyRow'
import { reviewHogProjectSettingsLogic } from 'products/review_hog/frontend/repositories/reviewHogProjectSettingsLogic'
import { reviewHogRepositoriesLogic } from 'products/review_hog/frontend/repositories/reviewHogRepositoriesLogic'
import { reviewHogSettingsLogic } from 'products/review_hog/frontend/reviewHogSettingsLogic'

import { ON_OFF_OPTIONS, OnOff, THRESHOLD_OPTIONS, projectDeepDefaults, toOnOff } from './deepReviewOptions'
import { InboxSection } from './InboxSection'
import { ReviewSkillsPanel } from './ReviewSkillsPanel'
import { SettingRow } from './SettingRow'
import { SettingsList } from './SettingsList'

/**
 * The viewer's select offers the project value as a follow option plus every other value. The
 * project value shows twice only while an own value equals it: one saved before the project value
 * changed. Picking "Same as project" then clears it.
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

/** The viewer's own review preferences. Nothing on this tab changes what other people get. */
export function MyPreferencesTab(): JSX.Element {
    const { settings, settingsLoading } = useValues(reviewHogSettingsLogic)
    const { updateSettings, followProjectDefault, setActiveTab } = useActions(reviewHogSettingsLogic)
    const { projectSettings, installations } = useValues(reviewHogProjectSettingsLogic)
    const { overview } = useValues(reviewHogRepositoriesLogic)
    const { setMyDefault } = useActions(reviewHogRepositoriesLogic)

    const disabledReason = settings === null ? 'Loading…' : settingsLoading ? 'Saving…' : undefined
    const myDefault = settings?.default_review_mode ?? 'follow'
    const project = projectDeepDefaults(projectSettings, settings)
    const ownThreshold = settings?.sources.urgency_threshold === 'user' ? settings.urgency_threshold : undefined
    const ownCelebrate =
        settings?.sources.celebrate_clean_reviews === 'user'
            ? toOnOff(settings.celebrate_clean_reviews ?? false)
            : undefined

    return (
        <>
            {projectSettings !== null && installations.length === 0 && (
                <LemonBanner
                    type="info"
                    action={{ children: 'Open Project settings', onClick: () => setActiveTab('project') }}
                >
                    Reviews start once GitHub is connected in Project settings.
                </LemonBanner>
            )}
            <SceneSection
                title="Standard reviews"
                description="Standard reviews run on every push and only comment on your pull request."
                titleHelper="Standard reviews never push to your branch. A pull request that already had a Deep review gets no more Standard reviews."
            >
                <SettingsList>
                    <SettingRow
                        title="Review my pull requests"
                        description={
                            myDefaultNotice(myDefault, overview?.my_choices_unlike_default ?? null) ??
                            'Choose whether your pull requests get a Standard review.'
                        }
                    >
                        <LemonSelect<DefaultReviewModeEnumApi>
                            size="small"
                            aria-label="Review my pull requests"
                            value={myDefault}
                            options={DEFAULT_REVIEW_MODE_OPTIONS}
                            onChange={(mode) => mode !== myDefault && setMyDefault(mode)}
                            disabledReason={disabledReason}
                            data-attr="review-hog-default-review-mode"
                        />
                    </SettingRow>
                    <SettingRow
                        title="Review my draft pull requests"
                        description="When off, a draft is reviewed once you mark it ready."
                    >
                        <LemonSwitch
                            aria-label="Review my draft pull requests"
                            checked={settings?.review_drafts ?? true}
                            onChange={(checked) => updateSettings({ review_drafts: checked })}
                            disabledReason={disabledReason}
                            data-attr="review-hog-review-drafts"
                        />
                    </SettingRow>
                </SettingsList>
                {installations.length > 0 && (
                    <LemonCollapse
                        panels={[
                            {
                                key: 'repositories',
                                header: 'Choose per repository',
                                content: <RepositoryList Row={RepositoryMyRow} hiddenView="exceptions" />,
                                dataAttr: 'review-hog-my-repository-choices',
                            },
                        ]}
                    />
                )}
            </SceneSection>

            <SceneSection
                title="Deep reviews"
                description="Deep reviews run on request and cost several times more than Standard."
                titleHelper="Start a Deep review with the Review button, the posthog-review label, or an Inbox report assigned to you. These preferences apply to the Deep reviews you start. A review someone else starts on your pull request uses their preferences, but only your own Resolve setting can push to your branch."
            >
                <SettingsList>
                    <SettingRow
                        title="Resolve comments on my pull requests"
                        description="A Deep review can push fix commits to your branch."
                        info="Only your own setting counts, whoever starts the review. PostHog Review pushes nothing while the pull request is in the merge queue, has another pull request stacked on it, or has no PostHog account behind it."
                    >
                        <LemonSwitch
                            aria-label="Resolve comments on my pull requests"
                            checked={settings?.resolve_comments ?? false}
                            onChange={(checked) => updateSettings({ resolve_comments: checked })}
                            disabledReason={disabledReason}
                            data-attr="review-hog-resolve-comments"
                        />
                    </SettingRow>
                    <SettingRow
                        title="Post findings at or above"
                        description="Findings below this stay in the review in PostHog."
                    >
                        <LemonSelect<UrgencyThresholdEnumApi | 'project'>
                            size="small"
                            aria-label="Mine: Post findings at or above"
                            value={ownThreshold ?? 'project'}
                            options={mineOptions(THRESHOLD_OPTIONS, project.threshold, ownThreshold)}
                            onChange={(value) =>
                                value === 'project'
                                    ? followProjectDefault('urgency_threshold')
                                    : updateSettings({ urgency_threshold: value })
                            }
                            disabledReason={disabledReason}
                            data-attr="review-hog-urgency-threshold"
                        />
                    </SettingRow>
                    <SettingRow
                        title="Celebrate clean reviews"
                        description="A review with no findings gets a small celebration."
                    >
                        <LemonSelect<OnOff | 'project'>
                            size="small"
                            aria-label="Mine: Celebrate clean reviews"
                            value={ownCelebrate ?? 'project'}
                            options={mineOptions(ON_OFF_OPTIONS, project.celebrate, ownCelebrate)}
                            onChange={(value) =>
                                value === 'project'
                                    ? followProjectDefault('celebrate_clean_reviews')
                                    : updateSettings({ celebrate_clean_reviews: value === 'on' })
                            }
                            disabledReason={disabledReason}
                            data-attr="review-hog-celebrate-clean-reviews"
                        />
                    </SettingRow>
                </SettingsList>
            </SceneSection>

            <ReviewSkillsPanel />
            <InboxSection />
        </>
    )
}
