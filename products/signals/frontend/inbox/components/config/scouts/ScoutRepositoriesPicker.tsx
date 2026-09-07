import { useMountedLogic, useValues } from 'kea'

import { LemonCollapse, LemonInputSelect, Link, Spinner } from '@posthog/lemon-ui'

import { resolveTeamGitHubIntegration, useRepositories } from 'lib/integrations/GitHubIntegrationHelpers'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { urls } from 'scenes/urls'

import { ScoutRepositoriesSummary } from './ScoutRepositoriesSummary'

/**
 * Mirrors `MAX_SCOUT_REPOSITORIES` on the scout config serializer. Held here rather than read from
 * the generated schema, which drops a list field's `max_length`.
 */
const MAX_REPOSITORIES = 10

const HELP_TEXT =
    'The repositories this scout clones into its sandbox. Set them for a scout that reads code, so it can search the tree and run the tests instead of reading files one at a time. Access stays read-only.'

interface ScoutRepositoriesPickerProps {
    /** Repositories pinned to this scout (`repositories`), each `organization/repo`. */
    selectedRepositories: string[]
    onChange: (repositories: string[]) => void
    /** Compact, collapsed row matching the inline scout settings form; the default suits the create dialog. */
    compact?: boolean
    disabledReason?: string
}

/**
 * Per-scout repository pin, persisted as the scout config's `repositories`. Offers the project's
 * GitHub connection, which is the one a scout's sandbox clones with, so every repository on
 * offer is one the scout can actually reach.
 */
export function ScoutRepositoriesPicker(props: ScoutRepositoriesPickerProps): JSX.Element {
    useMountedLogic(integrationsLogic)
    const { githubIntegrations, integrationsLoading } = useValues(integrationsLogic)
    const integration = resolveTeamGitHubIntegration(githubIntegrations)

    if (!integration) {
        return (
            <Shell
                {...props}
                loading={integrationsLoading}
                summary={
                    <ScoutRepositoriesSummary
                        loading={integrationsLoading}
                        repositories={props.selectedRepositories}
                        connected={false}
                    />
                }
            >
                {integrationsLoading ? (
                    <span className="flex items-center gap-2">
                        <Spinner /> Loading the GitHub connection...
                    </span>
                ) : (
                    <span>
                        <Link to={urls.settings('project-integrations')}>Connect GitHub to this project</Link> to let a
                        scout read your code.
                    </span>
                )}
            </Shell>
        )
    }
    return <Picker {...props} integrationId={integration.id} />
}

function Picker({ integrationId, ...props }: ScoutRepositoriesPickerProps & { integrationId: number }): JSX.Element {
    const { selectedRepositories, onChange, compact, disabledReason } = props
    const { options, loading } = useRepositories(integrationId, { valueKey: 'full_name' })
    // Plain `organization/repo` rows, not the shared hook's metadata row: a pin can hold ten
    // repositories, and a multi-line row per selected value would make the control taller than the
    // form around it. The row's "No write access" warning would also mislead here, since a scout
    // never pushes to a repository it reads.
    //
    // A pin can predate the current repository cache, so keep it as an option too. Opening the
    // picker must never silently drop a repository the scout is already using.
    const allOptions = [
        ...options.map(({ key, label }) => ({ key, label })),
        ...selectedRepositories
            .filter((repository) => !options.some((option) => option.key === repository))
            .map((repository) => ({ key: repository, label: repository })),
    ]

    return (
        <Shell
            {...props}
            loading={loading}
            summary={<ScoutRepositoriesSummary loading={loading} repositories={selectedRepositories} connected />}
        >
            <LemonInputSelect
                mode="multiple"
                value={selectedRepositories}
                onChange={onChange}
                options={allOptions}
                limit={MAX_REPOSITORIES}
                loading={loading}
                disabledReason={disabledReason}
                placeholder="Select repositories"
                size={compact ? 'small' : 'medium'}
                data-attr="scout-repositories"
            />
        </Shell>
    )
}

/**
 * The section around the control, so the loading, unconnected, and ready states all read as the
 * same row. Compact collapses behind a header carrying the pin, matching the Slack and write-access
 * rows either side of it in the settings form.
 */
function Shell({
    children,
    compact,
    summary,
}: ScoutRepositoriesPickerProps & {
    children: React.ReactNode
    loading: boolean
    summary: JSX.Element | null
}): JSX.Element {
    if (compact) {
        return (
            <div className="border-t border-primary pt-2">
                <LemonCollapse
                    embedded
                    size="small"
                    panels={[
                        {
                            key: 'repositories',
                            dataAttr: 'scout-repositories-panel',
                            header: (
                                <div className="flex flex-1 items-center justify-between gap-2">
                                    <span className="text-xs text-default">Repositories</span>
                                    <div className="flex flex-wrap items-center gap-1">{summary}</div>
                                </div>
                            ),
                            content: (
                                <div className="flex flex-col gap-2">
                                    <span className="text-[11.5px] text-muted">{HELP_TEXT}</span>
                                    {children}
                                </div>
                            ),
                        },
                    ]}
                />
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-3 border-t border-primary pt-4">
            <div className="flex flex-col gap-0.5">
                <span className="font-medium text-sm">Repositories</span>
                <p className="text-xs text-secondary mb-0">{HELP_TEXT}</p>
            </div>
            {children}
        </div>
    )
}
