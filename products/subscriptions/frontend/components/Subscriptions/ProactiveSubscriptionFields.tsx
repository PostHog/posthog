import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'

import type {
    ProactiveConfigApi,
    ProactiveConfigurationOptionsApi,
} from 'products/subscriptions/frontend/generated/api.schemas'

interface ProactiveSubscriptionFieldsProps {
    proactiveConfig?: ProactiveConfigApi | null
    options: ProactiveConfigurationOptionsApi | null
    optionsLoading: boolean
    optionsLoadFailed: boolean
    show: boolean
    onSelectRepository: (repository: string, repositoryIntegrationId: number) => void
    onRetry: () => void
}

function repositoryOptionKey(repository: string, repositoryIntegrationId: number): string {
    return JSON.stringify([repositoryIntegrationId, repository])
}

export function ProactiveSubscriptionFields({
    proactiveConfig,
    options,
    optionsLoading,
    optionsLoadFailed,
    show,
    onSelectRepository,
    onRetry,
}: ProactiveSubscriptionFieldsProps): JSX.Element | null {
    const pulseEnabled = useFeatureFlag('PULSE')

    if (!show || !pulseEnabled) {
        return null
    }

    if (optionsLoading) {
        return <LemonSkeleton.Row />
    }

    if (optionsLoadFailed) {
        return (
            <LemonBanner type="error">
                Couldn&apos;t load proactive settings.{' '}
                <LemonButton type="secondary" size="xsmall" onClick={onRetry}>
                    Try again
                </LemonButton>
            </LemonBanner>
        )
    }

    if (!options) {
        return null
    }

    const proactiveEnabled = proactiveConfig?.enabled === true
    const createDraftPullRequest = proactiveConfig?.create_draft_pr === true
    const selectedRepository =
        proactiveConfig?.repository && proactiveConfig.repository_integration_id
            ? repositoryOptionKey(proactiveConfig.repository, proactiveConfig.repository_integration_id)
            : null
    const draftPullRequestDisabledReason = !options.draft_pr_available
        ? 'Draft pull request preparation isn’t configured for this PostHog instance.'
        : !options.repositories.length
          ? 'No repositories are available. Connect GitHub with write access.'
          : undefined

    return (
        <div className="flex flex-col gap-3">
            <LemonField name={['proactive_config', 'enabled']}>
                {({ value, onChange }) => (
                    <LemonSwitch
                        checked={Boolean(value)}
                        onChange={onChange}
                        disabledReason={
                            options.proactive_available
                                ? undefined
                                : 'Proactive recommendations aren’t configured for this PostHog instance.'
                        }
                        bordered
                        fullWidth
                        data-attr="subscription-proactive-enabled"
                        label={
                            <div className="flex flex-col gap-1 py-1">
                                <div className="leading-tight">Look for follow-up recommendations</div>
                                <div className="text-xs text-secondary font-normal leading-tight">
                                    After each report, investigate changes and suggest a next step.
                                </div>
                            </div>
                        }
                    />
                )}
            </LemonField>
            {proactiveEnabled ? (
                <div className="flex flex-col gap-3 pl-2">
                    <LemonField name={['proactive_config', 'allow_public_web_research']}>
                        {({ value, onChange }) => (
                            <LemonSwitch
                                checked={value !== false}
                                onChange={onChange}
                                disabledReason={
                                    options.public_web_research_available
                                        ? undefined
                                        : 'Public web research isn’t configured for this PostHog instance.'
                                }
                                bordered
                                fullWidth
                                data-attr="subscription-proactive-public-research"
                                label={
                                    <div className="flex flex-col gap-1 py-1">
                                        <div className="leading-tight">Use public web research</div>
                                        <div className="text-xs text-secondary font-normal leading-tight">
                                            Search public webpages only when they help investigate a recommendation.
                                        </div>
                                    </div>
                                }
                            />
                        )}
                    </LemonField>
                    <LemonField name={['proactive_config', 'create_draft_pr']}>
                        {({ value, onChange }) => (
                            <LemonSwitch
                                checked={Boolean(value)}
                                onChange={onChange}
                                disabledReason={draftPullRequestDisabledReason}
                                bordered
                                fullWidth
                                data-attr="subscription-proactive-draft-pr"
                                label={
                                    <div className="flex flex-col gap-1 py-1">
                                        <div className="leading-tight">Prepare a draft pull request</div>
                                        <div className="text-xs text-secondary font-normal leading-tight">
                                            Build and test in an isolated sandbox before automatically opening a draft
                                            pull request.
                                        </div>
                                    </div>
                                }
                            />
                        )}
                    </LemonField>
                    <div className="text-xs text-secondary">
                        When eligible, PostHog may also prepare an experiment draft. It stays inactive until someone
                        starts it.
                    </div>
                    {createDraftPullRequest && options.draft_pr_available ? (
                        options.repositories.length ? (
                            <LemonField name={['proactive_config', 'repository']} label="Repository">
                                <LemonSelect
                                    value={selectedRepository}
                                    onChange={(value) => {
                                        const repository = options.repositories.find(
                                            (option) =>
                                                repositoryOptionKey(
                                                    option.repository,
                                                    option.repository_integration_id
                                                ) === value
                                        )
                                        if (repository) {
                                            onSelectRepository(
                                                repository.repository,
                                                repository.repository_integration_id
                                            )
                                        }
                                    }}
                                    options={options.repositories.map((repository) => ({
                                        label: repository.repository,
                                        value: repositoryOptionKey(
                                            repository.repository,
                                            repository.repository_integration_id
                                        ),
                                    }))}
                                    placeholder="Select a repository"
                                    data-attr="subscription-proactive-repository"
                                />
                            </LemonField>
                        ) : (
                            <LemonBanner type="info">
                                No repositories are currently available. Connect GitHub with write access, then refresh
                                this form.
                            </LemonBanner>
                        )
                    ) : null}
                </div>
            ) : null}
        </div>
    )
}
