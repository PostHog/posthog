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
    stamphogReviewRunsList,
} from '../../generated/api'
import type {
    ReviewRunApi,
    StamphogInstallInfoApi,
    StamphogRepoConfigApi,
    StamphogSyncInstallationResponseApi,
} from '../../generated/api.schemas'
import type { stamphogSceneLogicType } from './stamphogSceneLogicType'

// Only the most recent review runs are shown — this is a compact activity
// list, not a full history browser.
const REVIEW_RUNS_LIMIT = 20

export const stamphogSceneLogic = kea<stamphogSceneLogicType>([
    path(['products', 'stamphog', 'frontend', 'scenes', 'StamphogScene', 'stamphogSceneLogic']),

    connect(() => ({
        values: [teamLogic, ['currentProjectId']],
    })),

    actions({
        setRepoEnabled: (id: string, enabled: boolean) => ({ id, enabled }),
        setDigestEnabled: (id: string, enabled: boolean) => ({ id, enabled }),
        repoUpdateDone: (id: string) => ({ id }),
    }),

    loaders(({ values }) => ({
        repoConfigs: [
            [] as StamphogRepoConfigApi[],
            {
                loadRepoConfigs: async () => {
                    const response = await stamphogRepoConfigsList(String(values.currentProjectId))
                    return response.results
                },
            },
        ],
        reviewRuns: [
            [] as ReviewRunApi[],
            {
                loadReviewRuns: async () => {
                    const response = await stamphogReviewRunsList(String(values.currentProjectId), {
                        limit: REVIEW_RUNS_LIMIT,
                    })
                    return response.results
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
                syncInstallation: async ({ installationId }: { installationId: string }) => {
                    return stamphogRepoConfigsSyncInstallationCreate(String(values.currentProjectId), {
                        installation_id: installationId,
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
                repoUpdateDone: (state, { id }) => state.filter((x) => x !== id),
            },
        ],
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
            const installationId = searchParams.installation_id
            if (installationId) {
                actions.syncInstallation({ installationId: String(installationId) })
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadRepoConfigs()
        actions.loadReviewRuns()
        actions.loadInstallInfo()
    }),
])
