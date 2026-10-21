import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonInput, LemonSelect, Spinner } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import type { SentryMigrationCategoryEnumApi, SentryProjectApi } from '../../../generated/api.schemas'
import { errorTrackingEditAccessDisabledReason } from '../../../utils'
import { SentryMigrationItemCard } from './SentryMigrationItemCard'
import { SENTRY_CLOUD_URL, sentryMigrationLogic, sentryProjectKey } from './sentryMigrationLogic'
import { isSelectable } from './sentryMigrationSelection'

const CATEGORY_TITLES: Record<SentryMigrationCategoryEnumApi, string> = {
    rate_limit: 'Rate limits',
    error_message: 'Error message filters',
    release: 'Release filters',
    inbound_filter: 'Inbound filters',
}

function projectOptions(
    projects: SentryProjectApi[]
): { title: string; options: { value: string; label: string }[] }[] {
    const byOrganization = new Map<string, { title: string; options: { value: string; label: string }[] }>()
    for (const project of projects) {
        const section = byOrganization.get(project.organization_slug) ?? {
            title: project.organization_name,
            options: [],
        }
        section.options.push({ value: sentryProjectKey(project), label: project.project_name })
        byOrganization.set(project.organization_slug, section)
    }
    return Array.from(byOrganization.values())
}

export function SentryMigration(): JSX.Element {
    const {
        authToken,
        baseUrl,
        isConnected,
        projects,
        projectsLoading,
        selectedProjectKey,
        items,
        itemsLoading,
        selectedItemIds,
        importResultLoading,
    } = useValues(sentryMigrationLogic)
    const { setAuthToken, setBaseUrl, loadProjects, selectProject, toggleItem, applyImport, disconnect } =
        useActions(sentryMigrationLogic)
    const editAccessDisabledReason = errorTrackingEditAccessDisabledReason()

    if (!isConnected) {
        return (
            <div className="flex flex-col gap-3 max-w-160">
                <LemonField.Pure
                    label="Sentry auth token"
                    help={
                        <>
                            Create a personal token in Sentry under User settings &gt; Personal tokens, with the
                            org:read and project:read scopes. PostHog uses the token only to read your Sentry settings
                            and doesn't store it.
                        </>
                    }
                >
                    <LemonInput
                        type="password"
                        value={authToken}
                        onChange={setAuthToken}
                        onPressEnter={() => authToken && loadProjects()}
                        autoComplete="off"
                        data-attr="error-tracking-sentry-migration-token"
                    />
                </LemonField.Pure>
                <LemonField.Pure label="Sentry URL" help="Change this only if you host Sentry yourself.">
                    <LemonInput value={baseUrl} onChange={setBaseUrl} placeholder={SENTRY_CLOUD_URL} />
                </LemonField.Pure>
                <div>
                    <LemonButton
                        type="primary"
                        onClick={loadProjects}
                        loading={projectsLoading}
                        disabledReason={
                            editAccessDisabledReason ?? (!authToken.trim() ? 'Enter a Sentry auth token' : undefined)
                        }
                        data-attr="error-tracking-sentry-migration-connect"
                    >
                        Connect to Sentry
                    </LemonButton>
                </div>
            </div>
        )
    }

    const selectableCount = (items ?? []).filter(isSelectable).length

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-end gap-2">
                {projects && projects.length > 0 ? (
                    <LemonField.Pure label="Sentry project" className="min-w-60">
                        <LemonSelect
                            value={selectedProjectKey}
                            onChange={selectProject}
                            options={projectOptions(projects)}
                            placeholder="Select a project"
                            data-attr="error-tracking-sentry-migration-project"
                        />
                    </LemonField.Pure>
                ) : (
                    <LemonBanner type="info" className="grow">
                        This token can't see any Sentry projects. Check that its user is a member of the organization,
                        then connect again.
                    </LemonBanner>
                )}
                <LemonButton
                    type="secondary"
                    onClick={disconnect}
                    data-attr="error-tracking-sentry-migration-disconnect"
                >
                    Use another token
                </LemonButton>
            </div>

            {!selectedProjectKey ? null : itemsLoading || items === null ? (
                <Spinner />
            ) : items.length === 0 ? (
                <LemonBanner type="info">
                    This Sentry project has no filters or rate limits to import. Its default inbound filters are off,
                    and it has no custom error message or release filters.
                </LemonBanner>
            ) : (
                <>
                    {(Object.keys(CATEGORY_TITLES) as SentryMigrationCategoryEnumApi[]).map((category) => {
                        const categoryItems = items.filter((item) => item.category === category)
                        if (categoryItems.length === 0) {
                            return null
                        }
                        return (
                            <div key={category} className="flex flex-col gap-2">
                                <h4 className="mb-0">{CATEGORY_TITLES[category]}</h4>
                                {categoryItems.map((item) => (
                                    <SentryMigrationItemCard
                                        key={item.id}
                                        item={item}
                                        selected={selectedItemIds.includes(item.id)}
                                        disabledReason={
                                            item.fit === 'unsupported'
                                                ? "PostHog can't import this setting"
                                                : item.already_in_posthog
                                                  ? 'This project already has this setting'
                                                  : null
                                        }
                                        onToggle={() => toggleItem(item.id)}
                                    />
                                ))}
                            </div>
                        )
                    })}
                    <div className="flex flex-wrap items-center gap-2">
                        <LemonButton
                            type="primary"
                            onClick={applyImport}
                            loading={importResultLoading}
                            disabledReason={
                                editAccessDisabledReason ??
                                (selectableCount === 0
                                    ? 'Everything PostHog can import is already in this project'
                                    : selectedItemIds.length === 0
                                      ? 'Select at least one setting to import'
                                      : undefined)
                            }
                            data-attr="error-tracking-sentry-migration-import"
                        >
                            {selectedItemIds.length === 1
                                ? 'Import 1 setting'
                                : `Import ${selectedItemIds.length} settings`}
                        </LemonButton>
                        <span className="text-secondary text-xs">
                            Imported filters become suppression rules. You can edit or delete them afterwards.
                        </span>
                    </div>
                </>
            )}
        </div>
    )
}
