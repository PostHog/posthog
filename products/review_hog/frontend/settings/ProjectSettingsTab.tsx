import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSelect } from '@posthog/lemon-ui'

import { fullNameOrEmail } from 'lib/utils/strings'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import type {
    ReviewInstallationApi,
    ReviewProjectSettingsBotPullRequestsEnumApi,
    UrgencyThresholdEnumApi,
} from 'products/review_hog/frontend/generated/api.schemas'
import { InstallationClaims } from 'products/review_hog/frontend/repositories/InstallationClaims'
import { RepositoryList } from 'products/review_hog/frontend/repositories/RepositoryList'
import { RepositoryProjectRow } from 'products/review_hog/frontend/repositories/RepositoryProjectRow'
import { reviewHogProjectSettingsLogic } from 'products/review_hog/frontend/repositories/reviewHogProjectSettingsLogic'
import { RuleControls } from 'products/review_hog/frontend/repositories/RuleControls'
import { reviewHogSettingsLogic } from 'products/review_hog/frontend/reviewHogSettingsLogic'

import { ON_OFF_OPTIONS, OnOff, THRESHOLD_OPTIONS, toOnOff } from './deepReviewOptions'
import { SettingRow } from './SettingRow'
import { SettingsList } from './SettingsList'

/** Bot pull requests run as the person who connected GitHub, so the label names them when there is one. */
function botRunLabel(installations: readonly ReviewInstallationApi[]): string {
    const connectors = new Set(
        installations.flatMap((installation) =>
            installation.connected_by ? [fullNameOrEmail(installation.connected_by)] : []
        )
    )
    if (connectors.size === 1) {
        return `Reviewed, billed to ${[...connectors][0]}`
    }
    return 'Reviewed, billed to the person who connected GitHub'
}

/** The rules and defaults everyone in the project starts from. Only project admins can change them. */
export function ProjectSettingsTab(): JSX.Element {
    const { settings } = useValues(reviewHogSettingsLogic)
    const { projectSettings, canEdit, editDisabledReason, installations } = useValues(reviewHogProjectSettingsLogic)
    const { updateProjectSettings, addProjectPerson, removeProjectPerson } = useActions(reviewHogProjectSettingsLogic)

    const botPrs = projectSettings?.bot_prs ?? 'skip'
    // The project settings answer first after an admin edit; the personal settings reload after it.
    const threshold = projectSettings?.urgency_threshold ?? settings?.project_defaults.urgency_threshold ?? 'consider'
    const celebrate = toOnOff(
        projectSettings?.celebrate_clean_reviews ?? settings?.project_defaults.celebrate_clean_reviews ?? true
    )

    return (
        // Capped so a control stays close to the label it belongs to on a wide window.
        <div className="flex max-w-200 flex-col gap-8">
            {projectSettings !== null && !canEdit && (
                <LemonBanner type="info">Only project admins can change these settings.</LemonBanner>
            )}

            <SceneSection title="Repositories" description="Choose which repositories this project reviews.">
                <InstallationClaims />
            </SceneSection>

            <SceneSection
                title="Standard reviews"
                description="Standard reviews run on every push. These rules apply to everyone."
            >
                <SettingsList>
                    <SettingRow
                        title="Who gets reviews"
                        description="People can still choose for their own pull requests in My preferences."
                    >
                        <RuleControls
                            label="Project rule"
                            flashFor={projectSettings?.flash_for ?? 'off'}
                            people={projectSettings?.people ?? []}
                            canEdit={canEdit}
                            disabledReason={editDisabledReason}
                            onChangeFlashFor={(flashFor) => updateProjectSettings({ flash_for: flashFor })}
                            onAddPerson={(userId, kind) => addProjectPerson({ userId, kind })}
                            onRemovePerson={removeProjectPerson}
                            dataAttr="review-hog-project-flash-for"
                        />
                    </SettingRow>
                    <SettingRow
                        title="Bot pull requests"
                        description="Choose whether pull requests opened by bots get a review."
                    >
                        <LemonSelect<ReviewProjectSettingsBotPullRequestsEnumApi>
                            size="small"
                            aria-label="Bot pull requests"
                            value={botPrs}
                            options={[
                                { value: 'skip', label: 'Not reviewed' },
                                { value: 'run', label: botRunLabel(installations) },
                            ]}
                            onChange={(value) => value !== botPrs && updateProjectSettings({ bot_prs: value })}
                            disabledReason={editDisabledReason}
                            data-attr="review-hog-project-bot-prs"
                        />
                    </SettingRow>
                </SettingsList>
            </SceneSection>

            <SceneSection
                title="Deep reviews"
                description="Deep reviews run on request. Each person can override these defaults."
            >
                <SettingsList>
                    <SettingRow
                        title="Post findings at or above"
                        description="Findings below this stay in the review in PostHog."
                    >
                        <LemonSelect<UrgencyThresholdEnumApi>
                            size="small"
                            aria-label="Project: Post findings at or above"
                            value={threshold}
                            options={THRESHOLD_OPTIONS}
                            onChange={(value) => updateProjectSettings({ urgency_threshold: value })}
                            disabledReason={editDisabledReason}
                            data-attr="review-hog-project-urgency-threshold"
                        />
                    </SettingRow>
                    <SettingRow
                        title="Celebrate clean reviews"
                        description="A review with no findings gets a small celebration."
                    >
                        <LemonSelect<OnOff>
                            size="small"
                            aria-label="Project: Celebrate clean reviews"
                            value={celebrate}
                            options={ON_OFF_OPTIONS}
                            onChange={(value) => updateProjectSettings({ celebrate_clean_reviews: value === 'on' })}
                            disabledReason={editDisabledReason}
                            data-attr="review-hog-project-celebrate-clean-reviews"
                        />
                    </SettingRow>
                </SettingsList>
            </SceneSection>

            {installations.length > 0 && (
                <SceneSection
                    title="Repository rules"
                    description="Give a repository its own rule, or add and remove repositories."
                >
                    <RepositoryList Row={RepositoryProjectRow} otherTabView="mine" />
                </SceneSection>
            )}
        </div>
    )
}
