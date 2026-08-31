import { useActions, useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { urls } from 'scenes/urls'

import type { RepositoryOptionApi } from 'products/subscriptions/frontend/generated/api.schemas'

import { subscriptionLogic, SubscriptionFormType, SubscriptionLogicProps } from './subscriptionLogic'

function repositoryOptionKey(option: RepositoryOptionApi): string {
    return `${option.repository_integration_id}:${option.repository}`
}

export function ProactiveSubscriptionFields({
    logicProps,
    subscription,
}: {
    logicProps: SubscriptionLogicProps
    subscription: SubscriptionFormType
}): JSX.Element | null {
    const logic = subscriptionLogic(logicProps)
    const {
        proactiveConfigurationOptions,
        proactiveConfigurationOptionsLoadFailed,
        proactiveConfigurationOptionsLoading,
    } = useValues(logic)
    const {
        loadProactiveConfigurationOptions,
        selectProactiveRepository,
        setDraftPrEnabled,
        setProactiveEnabled,
        setPublicResearchSubject,
    } = useActions(logic)
    const config = subscription.proactive_config

    if (proactiveConfigurationOptionsLoading && !proactiveConfigurationOptions && !config?.enabled) {
        return <LemonSkeleton className="h-20 w-full" />
    }

    if (proactiveConfigurationOptionsLoadFailed && !proactiveConfigurationOptions && !config?.enabled) {
        return (
            <LemonBanner
                type="error"
                action={{
                    children: 'Retry',
                    onClick: loadProactiveConfigurationOptions,
                    loading: proactiveConfigurationOptionsLoading,
                    disabled: proactiveConfigurationOptionsLoading,
                }}
            >
                Could not load proactive configuration options.
            </LemonBanner>
        )
    }

    const proactiveAvailable = proactiveConfigurationOptions?.proactive_available === true
    const draftPrAvailable = proactiveConfigurationOptions?.draft_pr_available === true
    const showDraftPrControls = draftPrAvailable || config?.create_draft_pr === true
    if (!proactiveAvailable && !config?.enabled) {
        return null
    }

    const repositoryOptions = [...(proactiveConfigurationOptions?.repositories ?? [])]
    const configuredRepository =
        config?.repository && config.repository_integration_id
            ? {
                  repository: config.repository,
                  repository_integration_id: config.repository_integration_id,
              }
            : null
    if (
        configuredRepository &&
        !repositoryOptions.some((option) => repositoryOptionKey(option) === repositoryOptionKey(configuredRepository))
    ) {
        repositoryOptions.push(configuredRepository)
    }
    const repositoryCounts = repositoryOptions.reduce<Record<string, number>>((counts, option) => {
        counts[option.repository] = (counts[option.repository] ?? 0) + 1
        return counts
    }, {})
    const selectedRepositoryKey = configuredRepository ? repositoryOptionKey(configuredRepository) : null
    const repositorySelectOptions = repositoryOptions.map((option) => ({
        key: repositoryOptionKey(option),
        label:
            repositoryCounts[option.repository] > 1
                ? `${option.repository} (GitHub connection ${option.repository_integration_id})`
                : option.repository,
    }))
    const researchSubjects = proactiveConfigurationOptions?.public_research_subjects ?? []

    return (
        <div className="flex flex-col gap-3 rounded border bg-surface-primary p-3">
            {proactiveConfigurationOptionsLoadFailed && !proactiveConfigurationOptions ? (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Retry',
                        onClick: loadProactiveConfigurationOptions,
                        loading: proactiveConfigurationOptionsLoading,
                        disabled: proactiveConfigurationOptionsLoading,
                    }}
                >
                    Could not load proactive configuration options.
                </LemonBanner>
            ) : null}
            {!proactiveAvailable && !proactiveConfigurationOptionsLoadFailed ? (
                <LemonBanner type="warning">
                    Proactive follow-up is currently unavailable. You can turn off the existing setting, but PostHog
                    cannot run it until it is available again.
                </LemonBanner>
            ) : null}
            <LemonField name="proactive_config.enabled">
                <LemonSwitch
                    bordered
                    fullWidth
                    checked={config?.enabled === true}
                    onChange={setProactiveEnabled}
                    label={
                        <div className="flex flex-col gap-1 py-1">
                            <div className="leading-tight">Act on useful findings from future reports</div>
                            <div className="text-xs text-secondary font-normal leading-tight">
                                PostHog may prepare up to three recommendations, one draft pull request, and one
                                inactive experiment draft from each future report. You can turn this off at any time.
                            </div>
                        </div>
                    }
                    data-attr="subscription-proactive-enabled"
                />
            </LemonField>

            {config?.enabled ? (
                <>
                    {showDraftPrControls ? (
                        <>
                            {proactiveAvailable && !draftPrAvailable ? (
                                <LemonBanner type="warning">
                                    Draft pull request automation is currently unavailable. Turn it off to remove the
                                    saved setting.
                                </LemonBanner>
                            ) : null}
                            <LemonField name="proactive_config.create_draft_pr">
                                <LemonSwitch
                                    bordered
                                    fullWidth
                                    checked={config.create_draft_pr === true}
                                    onChange={setDraftPrEnabled}
                                    label={
                                        <div className="flex flex-col gap-1 py-1">
                                            <div className="leading-tight">
                                                Automatically open one draft pull request
                                            </div>
                                            <div className="text-xs text-secondary font-normal leading-tight">
                                                PostHog builds and tests the change in an isolated sandbox, then opens
                                                the draft only when the protected repository checks pass.
                                            </div>
                                        </div>
                                    }
                                    data-attr="subscription-proactive-draft-pr"
                                />
                            </LemonField>

                            {config.create_draft_pr ? (
                                <LemonField
                                    name="proactive_config.repository"
                                    label="Repository"
                                    help="Only repositories your personal GitHub connection can currently authorize are listed."
                                >
                                    <div>
                                        <LemonInputSelect
                                            mode="single"
                                            value={selectedRepositoryKey ? [selectedRepositoryKey] : []}
                                            onChange={(selectedKeys) => {
                                                const selected = repositoryOptions.find(
                                                    (option) => repositoryOptionKey(option) === selectedKeys[0]
                                                )
                                                selectProactiveRepository(selected ?? null)
                                            }}
                                            options={repositorySelectOptions}
                                            placeholder="Select a repository"
                                            disabledReason={
                                                draftPrAvailable
                                                    ? undefined
                                                    : 'Repository selection is currently unavailable. Turn off draft pull request automation to remove the saved repository.'
                                            }
                                            data-attr="subscription-proactive-repository"
                                        />
                                        {repositorySelectOptions.length === 0 ? (
                                            <LemonBanner type="info" className="mt-2">
                                                Connect GitHub under{' '}
                                                <Link to={urls.settings('user-personal-integrations')}>
                                                    Personal integrations
                                                </Link>{' '}
                                                to authorize a repository.
                                            </LemonBanner>
                                        ) : null}
                                    </div>
                                </LemonField>
                            ) : null}
                        </>
                    ) : null}

                    {researchSubjects.length > 0 ? (
                        <LemonField
                            name="proactive_config.public_research_subject_id"
                            label="Public research"
                            help="Optional. PostHog can only research a reviewed public subject from this list."
                        >
                            <LemonSelect
                                value={config.public_research_subject_id ?? null}
                                onChange={(subjectId) => setPublicResearchSubject(subjectId ?? null)}
                                options={[
                                    { value: null, label: 'Do not use public research' },
                                    ...researchSubjects.map((subject) => ({
                                        value: subject.id,
                                        label: `${subject.display_name} (${subject.canonical_domain})`,
                                    })),
                                ]}
                                disabledReason={
                                    proactiveAvailable ? undefined : 'Public research is currently unavailable.'
                                }
                                fullWidth
                            />
                        </LemonField>
                    ) : null}

                    <div className="text-xs text-secondary">
                        When eligible, PostHog may also prepare an inert experiment draft. It never starts an experiment
                        or sends traffic automatically.
                    </div>
                </>
            ) : null}
        </div>
    )
}
