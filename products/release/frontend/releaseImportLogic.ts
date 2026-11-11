import { MakeLogicType, actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { releasesImportAllCreate } from './generated/api'
import type { ReleaseDTOApi } from './generated/api.schemas'
import { releaseLogic } from './releaseLogic'

export type AutoImportState = 'idle' | 'running' | 'failed'

interface ReleaseImportLogicValues {
    currentProjectId: number | null
    releases: ReleaseDTOApi[]
    dataLoading: boolean
    loadFailed: boolean
    canEditReleases: boolean
    autoImportedProjects: Record<string, true>
    autoImportState: AutoImportState
    showAutoImport: boolean
}

interface ReleaseImportLogicActions {
    reload: (force?: boolean) => { force: boolean }
    loadReleasesSuccess: (releases: ReleaseDTOApi[]) => { releases: ReleaseDTOApi[] }
    runAutoImport: () => void
    setAutoImportState: (state: AutoImportState) => { state: AutoImportState }
    markAutoImported: (projectId: string) => { projectId: string }
}

type releaseImportLogicType = MakeLogicType<ReleaseImportLogicValues, ReleaseImportLogicActions>

export const releaseImportLogic = kea<releaseImportLogicType>([
    path(['products', 'release', 'frontend', 'releaseImportLogic']),
    connect(() => ({
        values: [releaseLogic, ['currentProjectId', 'releases', 'dataLoading', 'loadFailed', 'canEditReleases']],
        actions: [releaseLogic, ['reload', 'loadReleasesSuccess']],
    })),
    actions({
        runAutoImport: () => ({}),
        setAutoImportState: (state: AutoImportState) => ({ state }),
        markAutoImported: (projectId: string) => ({ projectId }),
    }),
    reducers({
        autoImportedProjects: [
            {} as Record<string, true>,
            { persist: true },
            { markAutoImported: (state, { projectId }) => ({ ...state, [projectId]: true as const }) },
        ],
        autoImportState: ['idle' as AutoImportState, { setAutoImportState: (_, { state }) => state }],
    }),
    selectors({
        showAutoImport: [
            (s) => [
                s.releases,
                s.dataLoading,
                s.loadFailed,
                s.canEditReleases,
                s.autoImportedProjects,
                s.currentProjectId,
            ],
            (
                releases: ReleaseDTOApi[],
                dataLoading: boolean,
                loadFailed: boolean,
                canEditReleases: boolean,
                autoImportedProjects: Record<string, true>,
                currentProjectId: number | null
            ) =>
                !dataLoading &&
                !loadFailed &&
                canEditReleases &&
                releases.length === 0 &&
                !autoImportedProjects[String(currentProjectId)],
        ],
    }),
    listeners(({ actions, values, cache }) => ({
        loadReleasesSuccess: () => {
            if (
                values.canEditReleases &&
                values.autoImportState === 'idle' &&
                !values.autoImportedProjects[String(values.currentProjectId)]
            ) {
                actions.runAutoImport()
            }
        },
        runAutoImport: async () => {
            const projectId = String(values.currentProjectId)
            actions.setAutoImportState('running')
            try {
                const { created_count } = await releasesImportAllCreate(projectId)
                if (cache.disposables.isDisposed) {
                    return
                }
                actions.markAutoImported(projectId)
                actions.setAutoImportState('idle')
                if (created_count) {
                    lemonToast.success(created_count === 1 ? 'Created 1 release' : `Created ${created_count} releases`)
                }
                actions.reload(true)
            } catch {
                if (cache.disposables.isDisposed) {
                    return
                }
                actions.setAutoImportState('failed')
            }
        },
    })),
])
