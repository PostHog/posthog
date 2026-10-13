import { useActions, useValues } from 'kea'

import { IconGithub } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSelect, LemonSkeleton } from '@posthog/lemon-ui'

import type { ReviewInstallationApi } from 'products/review_hog/frontend/generated/api.schemas'
import { SettingsList } from 'products/review_hog/frontend/settings/SettingsList'

import { projectName } from './repositoryChoices'
import { ClaimScopeChoice, reviewHogProjectSettingsLogic } from './reviewHogProjectSettingsLogic'
import { reviewHogRepositoriesLogic } from './reviewHogRepositoriesLogic'

function claimHint(installation: ReviewInstallationApi): string {
    if (installation.scope === 'all') {
        return 'This includes repositories created later, except ones another project selected.'
    }
    if (installation.scope === 'selected') {
        return 'New repositories are not reviewed until you include them under Repository rules.'
    }
    return 'Pick all repositories, or select some and include them under Repository rules.'
}

function InstallationClaim({ installation }: { installation: ReviewInstallationApi }): JSX.Element {
    const { editDisabledReason, claimSaving } = useValues(reviewHogProjectSettingsLogic)
    const { changeClaimScope } = useActions(reviewHogProjectSettingsLogic)
    const takenBy = installation.all_taken_by_project
    const scope: ClaimScopeChoice = installation.scope ?? 'none'

    return (
        <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 px-4 py-3">
            <div className="flex min-w-48 flex-1 items-center gap-3">
                <IconGithub className="size-6 shrink-0" />
                <div className="flex min-w-0 flex-col gap-0.5">
                    <span className="text-sm font-semibold">{installation.account_name}</span>
                    <span className="text-xs text-secondary">{claimHint(installation)}</span>
                </div>
            </div>
            <LemonSelect<ClaimScopeChoice>
                size="small"
                aria-label={`Repositories of ${installation.account_name} this project reviews`}
                value={scope}
                options={[
                    {
                        value: 'all',
                        label: 'All repositories',
                        disabledReason: takenBy
                            ? `${projectName(takenBy)} already reviews all repositories here`
                            : undefined,
                    },
                    { value: 'selected', label: 'Only selected repositories' },
                    { value: 'none', label: 'No repositories' },
                ]}
                onChange={(value) => changeClaimScope(installation, value)}
                disabledReason={claimSaving ? 'Saving…' : editDisabledReason}
                data-attr="review-hog-installation-claim"
            />
        </div>
    )
}

/** One claim per connected GitHub installation: which of its repositories this project reviews. */
export function InstallationClaims(): JSX.Element {
    const { projectSettings, projectSettingsLoadFailed, installations } = useValues(reviewHogProjectSettingsLogic)
    const { loadProjectSettings } = useActions(reviewHogProjectSettingsLogic)
    const { connectGitHubUrl } = useValues(reviewHogRepositoriesLogic)

    if (projectSettings === null) {
        return projectSettingsLoadFailed ? (
            <LemonBanner type="error" action={{ children: 'Retry', onClick: () => loadProjectSettings() }}>
                Could not load the project settings.
            </LemonBanner>
        ) : (
            <LemonSkeleton className="h-14 w-full" />
        )
    }
    if (installations.length === 0) {
        return (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded border border-primary bg-surface-primary px-4 py-3">
                <span className="text-sm text-secondary">
                    Connect GitHub to choose which repositories this project reviews.
                </span>
                <LemonButton
                    type="primary"
                    size="small"
                    icon={<IconGithub />}
                    to={connectGitHubUrl}
                    disableClientSideRouting
                    data-attr="review-hog-connect-github"
                >
                    Connect GitHub
                </LemonButton>
            </div>
        )
    }
    return (
        <SettingsList>
            {installations.map((installation) => (
                <InstallationClaim key={installation.installation_id} installation={installation} />
            ))}
        </SettingsList>
    )
}
