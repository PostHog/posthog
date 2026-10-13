import { useActions, useValues } from 'kea'

import { LemonSelect, LemonSwitch } from '@posthog/lemon-ui'

import { fullNameOrEmail } from 'lib/utils/strings'

import type {
    DefaultReviewModeEnumApi,
    ReviewInstallationApi,
    ReviewProjectSettingsBotPullRequestsEnumApi,
} from 'products/review_hog/frontend/generated/api.schemas'
import {
    DEFAULT_REVIEW_MODE_OPTIONS,
    myDefaultNotice,
} from 'products/review_hog/frontend/repositories/repositoryChoices'
import { reviewHogProjectSettingsLogic } from 'products/review_hog/frontend/repositories/reviewHogProjectSettingsLogic'
import { reviewHogRepositoriesLogic } from 'products/review_hog/frontend/repositories/reviewHogRepositoriesLogic'
import { RuleControls } from 'products/review_hog/frontend/repositories/RuleControls'
import { reviewHogSettingsLogic } from 'products/review_hog/frontend/reviewHogSettingsLogic'

import { SettingRow } from './SettingRow'
import { SettingsTable } from './SettingsTable'

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

/** Who gets a Standard review: the project rule, the viewer's own default, drafts, and bot pull requests. */
export function StandardSettingsSection(): JSX.Element {
    const { settings, settingsLoading } = useValues(reviewHogSettingsLogic)
    const { updateSettings } = useActions(reviewHogSettingsLogic)
    const { projectSettings, canEdit, editDisabledReason, installations } = useValues(reviewHogProjectSettingsLogic)
    const { updateProjectSettings, addProjectPerson, removeProjectPerson } = useActions(reviewHogProjectSettingsLogic)
    const { overview } = useValues(reviewHogRepositoriesLogic)
    const { setMyDefault } = useActions(reviewHogRepositoriesLogic)

    const myDefault = settings?.default_review_mode ?? 'follow'
    const reviewDrafts = settings?.review_drafts ?? true
    const botPrs = projectSettings?.bot_prs ?? 'skip'
    const mineDisabledReason = settings === null ? 'Loading…' : settingsLoading ? 'Saving…' : undefined
    const notice = myDefaultNotice(myDefault, overview?.my_choices_unlike_default ?? null)

    return (
        <SettingsTable>
            <SettingRow
                title="Automatic reviews"
                description="Choose who gets a Standard review on every push."
                project={
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
                }
                mine={
                    <div className="flex min-w-0 flex-col items-start gap-1">
                        <LemonSelect<DefaultReviewModeEnumApi>
                            size="small"
                            aria-label="Automatic review on my PRs"
                            value={myDefault}
                            options={DEFAULT_REVIEW_MODE_OPTIONS}
                            onChange={(mode) => mode !== myDefault && setMyDefault(mode)}
                            disabledReason={mineDisabledReason}
                            data-attr="review-hog-default-review-mode"
                        />
                        {notice && <span className="text-xs text-secondary">{notice}</span>}
                    </div>
                }
            />
            <SettingRow
                title="Draft pull requests"
                description="When off, a draft gets its first automatic review when you mark it ready for review."
                project={<span className="text-xs text-secondary">Personal only</span>}
                mine={
                    <LemonSwitch
                        aria-label="Review my draft pull requests"
                        checked={reviewDrafts}
                        onChange={(checked) => updateSettings({ review_drafts: checked })}
                        disabledReason={mineDisabledReason}
                        data-attr="review-hog-review-drafts"
                    />
                }
            />
            <SettingRow
                title="Bot pull requests"
                description="Choose whether pull requests opened by bots get a review."
                project={
                    <LemonSelect<ReviewProjectSettingsBotPullRequestsEnumApi>
                        size="small"
                        className="min-w-0 shrink"
                        truncateText={{ maxWidthClass: 'max-w-full' }}
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
                }
                mine={<span className="text-xs text-secondary">Project only</span>}
            />
        </SettingsTable>
    )
}
