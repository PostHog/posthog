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
    StamphogSyncInstallationRequestApi,
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
        redirectToAuthorize: true,
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
                    // Optional: absent on the authorize-first redirect, where the backend discovers the
                    // caller's installations from the code instead of trusting a supplied id.
                    installationId?: string
                    code: string
                    state: string
                }) => {
                    const body: StamphogSyncInstallationRequestApi = { code, state }
                    if (installationId) {
                        body.installation_id = installationId
                    }
                    return stamphogRepoConfigsSyncInstallationCreate(String(values.currentProjectId), body)
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
        authorizeUrl: [
            (s) => [s.installInfo],
            (installInfo: StamphogInstallInfoApi | null): string => installInfo?.authorize_url ?? '',
        ],
        appNotInstalled: [
            (s) => [s.syncResult],
            (syncResult: StamphogSyncInstallationResponseApi | null): boolean => syncResult?.app_not_installed ?? false,
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
        redirectToAuthorize: async () => {
            // The setup_action=update redirect carries no code (nothing to sync), so bounce the browser
            // through the authorize URL for one silent hop — GitHub redirects straight back with a code
            // and the discovery path takes over. Fetch install info directly rather than racing the loader,
            // which may not have resolved yet when the callback fires.
            const info = await stamphogRepoConfigsInstallInfoRetrieve(String(values.currentProjectId))
            if (info.authorize_url) {
                window.location.href = info.authorize_url
            } else {
                lemonToast.error('GitHub App is not configured, so it cannot be connected')
            }
        },
        syncInstallationSuccess: ({ syncResult }) => {
            // Drop the callback params from the URL so a refresh doesn't re-sync,
            // then refresh the list to show the newly bound repos.
            router.actions.replace(urls.stamphog())
            if (syncResult?.app_not_installed) {
                // Discovery found no installation the user can reach — they still need to install the App.
                // The banner and connect button surface the install link.
                lemonToast.info("Stamphog isn't installed on GitHub yet. Use the install link to add it.")
            }
            actions.loadRepoConfigs()
        },
        syncInstallationFailure: () => {
            lemonToast.error('Could not connect the GitHub App installation')
        },
    })),

    urlToAction(({ actions }) => ({
        [urls.stamphogCallback()]: (_, searchParams) => {
            // Two redirects land here, both carrying the state token we minted in install_info:
            //   - authorize/fresh-install: a user OAuth code (+ installation_id on a fresh install). The
            //     backend proves ownership from the code and discovers or verifies the installation.
            //   - setup_action=update (app already installed): installation_id + state but NO code. The id
            //     is user-editable and not trusted, so restart via authorize to obtain a real code.
            const installationId = searchParams.installation_id
            const code = searchParams.code
            const state = searchParams.state
            if (code && state) {
                actions.syncInstallation({
                    installationId: installationId ? String(installationId) : undefined,
                    code: String(code),
                    state: String(state),
                })
            } else if (installationId && state) {
                actions.redirectToAuthorize()
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadRepoConfigs()
        actions.loadInstallInfo()
    }),
])
