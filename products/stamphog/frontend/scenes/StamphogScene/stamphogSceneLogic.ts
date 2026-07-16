import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import {
    stamphogRepoConfigsInstallInfoRetrieve,
    stamphogRepoConfigsList,
    stamphogRepoConfigsPartialUpdate,
    stamphogRepoConfigsSyncInstallationCreate,
} from '../../generated/api'
import type {
    ReviewModeEnumApi,
    StamphogInstallInfoApi,
    StamphogRepoConfigApi,
    StamphogSyncInstallationResponseApi,
} from '../../generated/api.schemas'
import type { stamphogSceneLogicType } from './stamphogSceneLogicType'

export const stamphogSceneLogic = kea<stamphogSceneLogicType>([
    path(['products', 'stamphog', 'frontend', 'scenes', 'StamphogScene', 'stamphogSceneLogic']),

    connect(() => ({
        values: [teamLogic, ['currentProjectId']],
    })),

    actions({
        setRepoEnabled: (id: string, enabled: boolean) => ({ id, enabled }),
        setDigestEnabled: (id: string, enabled: boolean) => ({ id, enabled }),
        setReviewMode: (id: string, reviewMode: ReviewModeEnumApi) => ({ id, reviewMode }),
        setTriggerLabel: (id: string, triggerLabel: string) => ({ id, triggerLabel }),
        repoUpdateDone: (id: string) => ({ id }),
        setRepoSearch: (search: string) => ({ search }),
    }),

    loaders(({ values }) => ({
        repoConfigs: [
            [] as StamphogRepoConfigApi[],
            {
                loadRepoConfigs: async () => {
                    // A GitHub installation can surface hundreds of repos, so follow LimitOffset
                    // pagination and fetch every page. The table searches and paginates this list
                    // client-side, so a truncated first page would hide repos that then can't be found
                    // or toggled — the whole point of the toggle list.
                    const pageSize = 100
                    const all: StamphogRepoConfigApi[] = []
                    for (let offset = 0; ; offset += pageSize) {
                        const response = await stamphogRepoConfigsList(String(values.currentProjectId), {
                            limit: pageSize,
                            offset,
                        })
                        all.push(...response.results)
                        if (all.length >= response.count || response.results.length === 0) {
                            break
                        }
                    }
                    return all
                },
            },
        ],
        installInfo: [
            null as StamphogInstallInfoApi | null,
            {
                loadInstallInfo: async () => {
                    return stamphogRepoConfigsInstallInfoRetrieve(String(values.currentProjectId))
                },
            },
        ],
        // Sync is a loader so the button can wire its in-flight state off
        // syncResultLoading and guard double-submission during the callback.
        syncResult: [
            null as StamphogSyncInstallationResponseApi | null,
            {
                syncInstallation: async ({
                    installationId,
                    code,
                    state,
                }: {
                    installationId: string
                    code: string
                    state: string
                }) => {
                    return stamphogRepoConfigsSyncInstallationCreate(String(values.currentProjectId), {
                        installation_id: installationId,
                        code,
                        state,
                    })
                },
            },
        ],
    })),

    reducers({
        // Repos with an in-flight PATCH — used to disable their switches so a
        // second toggle can't fire before the first resolves.
        updatingRepoIds: [
            [] as string[],
            {
                setRepoEnabled: (state, { id }) => (state.includes(id) ? state : [...state, id]),
                setDigestEnabled: (state, { id }) => (state.includes(id) ? state : [...state, id]),
                setReviewMode: (state, { id }) => (state.includes(id) ? state : [...state, id]),
                setTriggerLabel: (state, { id }) => (state.includes(id) ? state : [...state, id]),
                repoUpdateDone: (state, { id }) => state.filter((x) => x !== id),
            },
        ],
        repoSearch: ['', { setRepoSearch: (_, { search }) => search }],
    }),

    selectors({
        installUrl: [
            (s) => [s.installInfo],
            (installInfo: StamphogInstallInfoApi | null): string => installInfo?.install_url ?? '',
        ],
        syncedRepos: [
            (s) => [s.syncResult],
            (syncResult: StamphogSyncInstallationResponseApi | null): readonly StamphogRepoConfigApi[] =>
                syncResult?.synced ?? [],
        ],
        skippedRepos: [
            (s) => [s.syncResult],
            (syncResult: StamphogSyncInstallationResponseApi | null): readonly string[] => syncResult?.skipped ?? [],
        ],
        // A GitHub App install can surface hundreds of repos, so the table filters client-side by name.
        filteredRepoConfigs: [
            (s) => [s.repoConfigs, s.repoSearch],
            (repoConfigs: StamphogRepoConfigApi[], repoSearch: string): StamphogRepoConfigApi[] => {
                const needle = repoSearch.trim().toLowerCase()
                if (!needle) {
                    return repoConfigs
                }
                return repoConfigs.filter((repo) => repo.repository.toLowerCase().includes(needle))
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        setRepoEnabled: async ({ id, enabled }) => {
            try {
                await stamphogRepoConfigsPartialUpdate(String(values.currentProjectId), id, { enabled })
                actions.loadRepoConfigs()
            } catch {
                lemonToast.error('Failed to update repository')
            } finally {
                actions.repoUpdateDone(id)
            }
        },
        setDigestEnabled: async ({ id, enabled }) => {
            try {
                await stamphogRepoConfigsPartialUpdate(String(values.currentProjectId), id, { digest_enabled: enabled })
                actions.loadRepoConfigs()
            } catch {
                lemonToast.error('Failed to update digest setting')
            } finally {
                actions.repoUpdateDone(id)
            }
        },
        setReviewMode: async ({ id, reviewMode }) => {
            try {
                await stamphogRepoConfigsPartialUpdate(String(values.currentProjectId), id, {
                    review_mode: reviewMode,
                })
                actions.loadRepoConfigs()
            } catch {
                lemonToast.error('Failed to update review mode')
            } finally {
                actions.repoUpdateDone(id)
            }
        },
        setTriggerLabel: async ({ id, triggerLabel }) => {
            try {
                await stamphogRepoConfigsPartialUpdate(String(values.currentProjectId), id, {
                    trigger_label: triggerLabel,
                })
                actions.loadRepoConfigs()
            } catch {
                lemonToast.error('Failed to update trigger label')
            } finally {
                actions.repoUpdateDone(id)
            }
        },
        syncInstallationSuccess: () => {
            // Drop installation_id from the URL so a refresh doesn't re-sync,
            // then refresh the list to show the newly bound repos.
            router.actions.replace(urls.stamphog())
            actions.loadRepoConfigs()
        },
        syncInstallationFailure: () => {
            lemonToast.error('Could not connect the GitHub App installation')
        },
    })),

    urlToAction(({ actions }) => ({
        [urls.stamphogCallback()]: (_, searchParams) => {
            // The GitHub setup redirect carries installation_id, a user OAuth code, and the state token
            // we minted in install_info. The backend needs the code to prove installation ownership and
            // the state to prove this callback belongs to the current team's own install flow.
            const installationId = searchParams.installation_id
            const code = searchParams.code
            const state = searchParams.state
            if (installationId && code && state) {
                actions.syncInstallation({
                    installationId: String(installationId),
                    code: String(code),
                    state: String(state),
                })
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadRepoConfigs()
        actions.loadInstallInfo()
    }),
])
