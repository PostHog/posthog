import { useActions, useValues } from 'kea'

import { IconGithub } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSelect, LemonSkeleton } from '@posthog/lemon-ui'

import type { ReviewInstallationApi } from 'products/review_hog/frontend/generated/api.schemas'

import { projectName } from './repositoryChoices'
import { ClaimScopeChoice, reviewHogProjectSettingsLogic } from './reviewHogProjectSettingsLogic'
import { reviewHogRepositoriesLogic } from './reviewHogRepositoriesLogic'

function claimHint(installation: ReviewInstallationApi): string {
    if (installation.scope === 'all') {
        return 'Includes future repositories. Repositories selected by another project stay there.'
    }
    if (installation.scope === 'selected') {
        return 'Add repositories below to review them.'
    }
    return 'Choose which repositories to review.'
}

function InstallationClaim({ installation }: { installation: ReviewInstallationApi }): JSX.Element {
    const { editDisabledReason, claimSaving } = useValues(reviewHogProjectSettingsLogic)
    const { changeClaimScope } = useActions(reviewHogProjectSettingsLogic)
    const takenBy = installation.all_taken_by_project
    const scope: ClaimScopeChoice = installation.scope ?? 'none'

    return (
        <div className="flex flex-wrap items-center gap-3 rounded border border-primary bg-surface-primary px-4 py-2.5">
            <IconGithub className="size-6 shrink-0" />
            <div className="flex min-w-0 flex-1 basis-72 flex-col gap-0.5">
                <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold">{installation.account_name}</span>
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
                <span className="text-xs text-secondary">{claimHint(installation)}</span>
            </div>
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
                <span className="text-sm text-secondary">Connect GitHub to add repositories.</span>
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
        <div className="flex flex-col gap-2">
            {installations.map((installation) => (
                <InstallationClaim key={installation.installation_id} installation={installation} />
            ))}
        </div>
    )
}
