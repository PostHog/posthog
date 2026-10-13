import { useActions, useValues } from 'kea'

import { IconGithub } from '@posthog/icons'
import { LemonBanner, LemonInputSelect, LemonSelect } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { GitHubRepositoryPicker } from 'lib/integrations/GitHubIntegrationHelpers'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { PropertyDefinition, PropertyDefinitionType, PropertyType } from '~/types'

import { HogFlowPropertyFilters } from 'products/workflows/frontend/Workflows/hogflows/filters/HogFlowFilters'
import { registerTriggerType } from 'products/workflows/frontend/Workflows/hogflows/registry/triggers/triggerTypeRegistry'
import { workflowLogic } from 'products/workflows/frontend/Workflows/workflowLogic'

import {
    GITHUB_ACTOR_MODE_OPTIONS,
    GITHUB_EVENT_TYPE_OPTIONS,
    GithubActorMode,
    decodeGithubFilters,
    encodeGithubFilters,
    InternalEventGithubTriggerConfig,
    isGithubEventTriggerConfig,
} from './githubTriggerFilters'

// GitHub deliveries never reach ClickHouse, so the advanced list has no stored values to
// autocomplete from and the properties have to be declared.
const ADVANCED_PROPERTIES: { key: string; type: PropertyType }[] = [
    { key: 'action', type: PropertyType.String },
    { key: 'title', type: PropertyType.String },
    { key: 'body', type: PropertyType.String },
    { key: 'branch', type: PropertyType.String },
    { key: 'author_association', type: PropertyType.String },
    // A string ('private'/'public'), not a boolean - GitHub deliveries never reach ClickHouse, so
    // an exact-match filter has no stored property definition to coerce a raw boolean against.
    { key: 'repository_visibility', type: PropertyType.String },
    // Only carried by a pull request review: approved, changes_requested or commented.
    { key: 'review_state', type: PropertyType.String },
]

const ADVANCED_PROPERTY_DEFINITIONS: PropertyDefinition[] = ADVANCED_PROPERTIES.map(({ key, type }) => ({
    id: `github-event-${key}`,
    name: key,
    type: PropertyDefinitionType.Event,
    property_type: type,
}))

function StepTriggerConfigurationGithubEvent({ node }: { node: any }): JSX.Element {
    const { setWorkflowActionConfig } = useActions(workflowLogic)
    const { actionValidationErrorsById } = useValues(workflowLogic)
    const { integrations, integrationsLoading } = useValues(integrationsLogic)

    const config = node.data.config as InternalEventGithubTriggerConfig
    const filters = decodeGithubFilters(config.filters?.properties)
    const validationResult = actionValidationErrorsById[node.data.id]
    const githubIntegrations = (integrations ?? []).filter((integration) => integration.kind === 'github')

    const update = (changes: Partial<typeof filters>): void => {
        setWorkflowActionConfig(node.data.id, {
            type: 'internal-event',
            filters: {
                source: 'internal-events',
                events: [{ id: '$github_event_received', type: 'events' }],
                properties: encodeGithubFilters({ ...filters, ...changes }),
            },
        })
    }

    if (integrationsLoading) {
        return <p className="mb-0 text-sm text-muted-alt">Loading GitHub connections…</p>
    }

    if (githubIntegrations.length === 0) {
        return (
            <LemonBanner type="warning" className="w-full">
                <p className="mb-0">
                    This trigger needs a GitHub connection, and this project doesn't have one yet. Install the GitHub
                    app on the repositories you want, then come back and pick one.{' '}
                    <Link to={urls.settings('project-integrations')} className="font-semibold">
                        Connect GitHub
                    </Link>
                </p>
            </LemonBanner>
        )
    }

    return (
        <div className="flex flex-col gap-2 w-full">
            <p className="mb-0 text-sm text-muted-alt">
                This workflow runs once for each matching GitHub delivery. Runs have no associated person, so
                person-dependent steps are unavailable.
            </p>

            <LemonField.Pure
                label="Repository"
                error={validationResult?.errors?.repository}
                info="PostHog only receives events from repositories the GitHub app is installed on."
            >
                <GitHubRepositoryPicker
                    integrationId={githubIntegrations[0].id}
                    value={filters.repository ?? ''}
                    onChange={(value) => update({ repository: value })}
                    valueKey="full_name"
                />
            </LemonField.Pure>

            <LemonField.Pure
                label="What starts a run"
                error={validationResult?.errors?.eventTypes}
                info="Pick at least one. Every delivery of that kind on the repository starts a run."
            >
                <LemonInputSelect
                    mode="multiple"
                    value={filters.eventTypes}
                    options={GITHUB_EVENT_TYPE_OPTIONS.map(({ value, label }) => ({ key: value, label }))}
                    placeholder="Select the events to listen for"
                    onChange={(eventTypes) => update({ eventTypes })}
                    data-attr="github-trigger-event-types"
                />
            </LemonField.Pure>

            <LemonField.Pure
                label="Who can start a run"
                info="Anyone on the internet can open an issue or comment on a public repository, so this decides whose text a run is allowed to act on."
            >
                <LemonSelect<GithubActorMode>
                    value={filters.actorMode}
                    options={GITHUB_ACTOR_MODE_OPTIONS.map(({ value, label, description }) => ({
                        value,
                        label,
                        labelInMenu: (
                            <div className="flex flex-col py-1">
                                <span>{label}</span>
                                <span className="text-xs text-muted-alt">{description}</span>
                            </div>
                        ),
                    }))}
                    onChange={(actorMode) => update({ actorMode, actorLogins: [] })}
                    data-attr="github-trigger-actor-mode"
                />
            </LemonField.Pure>

            {filters.actorMode === 'specific_people' && (
                <LemonField.Pure label="GitHub usernames" error={validationResult?.errors?.actorLogins}>
                    <LemonInputSelect
                        mode="multiple"
                        allowCustomValues
                        value={filters.actorLogins}
                        options={filters.actorLogins.map((login) => ({ key: login, label: login }))}
                        placeholder="GitHub usernames, e.g. octocat"
                        onChange={(actorLogins) => update({ actorLogins })}
                        data-attr="github-trigger-actor-logins"
                    />
                </LemonField.Pure>
            )}

            {filters.actorMode !== 'write_access' && (
                <LemonBanner type="warning" className="w-full">
                    <p className="mb-0">
                        A run can now start from text written by someone with no access to the repository. Don't pass
                        that text to a step that acts on it, such as creating a task.
                    </p>
                </LemonBanner>
            )}

            <LemonField.Pure
                label="Additional filters"
                info="Match on the action, title, body, or other fields of the delivery."
            >
                <HogFlowPropertyFilters
                    filtersKey={`github-event-trigger-${node.data.id}`}
                    filters={{ properties: filters.additional }}
                    setFilters={(next) => update({ additional: next?.properties ?? [] })}
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                    propertyAllowList={{
                        [TaxonomicFilterGroupType.EventProperties]: ADVANCED_PROPERTIES.map((p) => p.key),
                    }}
                    propertyDefinitionsOverride={ADVANCED_PROPERTY_DEFINITIONS}
                    taxonomicFilterOptionsFromProp={{
                        [TaxonomicFilterGroupType.EventProperties]: ADVANCED_PROPERTIES.map((p) => ({ name: p.key })),
                    }}
                    inline
                />
            </LemonField.Pure>
        </div>
    )
}

registerTriggerType({
    // The tile's own identity, not the stored config type: `internal-event` carries every internal
    // event, so naming the tile after it would make the GitHub tile claim all of them.
    value: 'github-event',
    label: 'GitHub activity',
    icon: <IconGithub />,
    description: 'Trigger when something happens on a GitHub repository',
    group: 'GitHub',
    featureFlag: 'github-workflow-triggers',
    matchConfig: (config) => isGithubEventTriggerConfig(config),
    buildConfig: () => ({
        type: 'internal-event',
        filters: {
            source: 'internal-events',
            events: [{ id: '$github_event_received', type: 'events' }],
            properties: encodeGithubFilters({
                repository: null,
                eventTypes: [],
                actorMode: 'write_access',
                actorLogins: [],
                additional: [],
            }),
        },
    }),
    validate: (config): { valid: boolean; errors: Record<string, string> } | null => {
        if (!isGithubEventTriggerConfig(config)) {
            return null
        }
        const filters = decodeGithubFilters(config.filters?.properties)
        if (!filters.repository) {
            return { valid: false, errors: { repository: 'Please pick a repository' } }
        }
        if (!filters.eventTypes.length) {
            return { valid: false, errors: { eventTypes: 'Pick at least one event, or the trigger will never fire' } }
        }
        if (filters.actorMode === 'specific_people' && !filters.actorLogins.length) {
            return {
                valid: false,
                errors: { actorLogins: 'Add at least one username, or the trigger will never fire' },
            }
        }
        return { valid: true, errors: {} }
    },
    ConfigComponent: StepTriggerConfigurationGithubEvent,
})
