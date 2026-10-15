import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { fullNameOrEmail } from 'lib/utils/strings'

import type {
    ReviewInstallationApi,
    ReviewProjectSettingsBotPullRequestsEnumApi,
} from 'products/review_hog/frontend/generated/api.schemas'

import { reviewHogProjectSettingsLogic } from './reviewHogProjectSettingsLogic'
import { RuleControls } from './RuleControls'

/** Bot pull requests run as the person who connected GitHub, so the label names them when there is one. */
function botRunLabel(installations: readonly ReviewInstallationApi[]): string {
    const connectors = new Set(
        installations.flatMap((installation) =>
            installation.connected_by ? [fullNameOrEmail(installation.connected_by)] : []
        )
    )
    if (connectors.size === 1) {
        return `Automatic review, billed to ${[...connectors][0]} (connected GitHub)`
    }
    return 'Automatic review, billed to the person who connected GitHub'
}

export function ProjectRuleCell({ className }: { className?: string }): JSX.Element {
    const { projectSettings, canEdit, editDisabledReason, installations } = useValues(reviewHogProjectSettingsLogic)
    const { updateProjectSettings, addProjectPerson, removeProjectPerson } = useActions(reviewHogProjectSettingsLogic)
    const botPrs = projectSettings?.bot_prs ?? 'skip'

    return (
        <div className={`flex min-w-0 flex-col gap-2 px-4 py-3 ${className ?? ''}`}>
            <div className="flex flex-col gap-0.5">
                <span className="text-sm font-semibold">Project settings</span>
                <span className="text-xs text-secondary">
                    Every repository without an exception starts here. Starts at opt-in only, so connecting GitHub never
                    starts reviews everywhere.
                </span>
            </div>
            <RuleControls
                label="Project settings"
                flashFor={projectSettings?.flash_for ?? 'off'}
                people={projectSettings?.people ?? []}
                canEdit={canEdit}
                disabledReason={editDisabledReason}
                onChangeFlashFor={(flashFor) => updateProjectSettings({ flash_for: flashFor })}
                onAddPerson={(userId, kind) => addProjectPerson({ userId, kind })}
                onRemovePerson={removeProjectPerson}
                dataAttr="review-hog-project-flash-for"
            />
            <span className="text-xs text-secondary">
                People opt in under My pull requests, with their default or a choice for one repository.
            </span>
            <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs text-secondary">Bot PRs, all repositories:</span>
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
                    className="max-w-full"
                    data-attr="review-hog-project-bot-prs"
                />
            </div>
        </div>
    )
}
