import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { projectLogic } from 'scenes/projectLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import type { UserType } from '~/types'

import { earlyAccessFeatureList } from 'products/early_access_features/frontend/generated/api'
import type { EarlyAccessFeatureApi } from 'products/early_access_features/frontend/generated/api.schemas'
import { experimentsList } from 'products/experiments/frontend/generated/api'
import type { ExperimentBasicApi } from 'products/experiments/frontend/generated/api.schemas'
import { featureFlagsList, scheduledChangesList } from 'products/feature_flags/frontend/generated/api'
import type { FeatureFlagApi, ScheduledChangeApi } from 'products/feature_flags/frontend/generated/api.schemas'

import { releasesCreate, releasesList, releasesPartialUpdate } from './generated/api'
import type { PatchedWriteReleaseApi, ReleaseDTOApi } from './generated/api.schemas'
import { ReleaseRow, ReleaseStage, buildReleaseRow } from './releaseUtils'

interface ReleaseLogicValues {
    currentProjectId: number | null
    user: UserType | null
    releases: ReleaseDTOApi[]
    releasesLoading: boolean
    flags: FeatureFlagApi[]
    experiments: ExperimentBasicApi[]
    earlyAccessFeatures: EarlyAccessFeatureApi[]
    scheduledChanges: ScheduledChangeApi[]
    search: string
    stageFilter: ReleaseStage | null
    decisionOnly: boolean
    newReleaseOpen: boolean
    scheduleFlagId: number | null
    flagsLoading: boolean
    experimentsLoading: boolean
    dataLoading: boolean
    rows: ReleaseRow[]
    filteredRows: ReleaseRow[]
    decisionRows: ReleaseRow[]
}

interface ReleaseLogicActions {
    loadReleases: () => void
    loadFlags: () => void
    loadExperiments: () => void
    loadEarlyAccessFeatures: () => void
    loadScheduledChanges: () => void
    setSearch: (search: string) => { search: string }
    setStageFilter: (stage: ReleaseStage | null) => { stage: ReleaseStage | null }
    setDecisionOnly: (decisionOnly: boolean) => { decisionOnly: boolean }
    setNewReleaseOpen: (open: boolean) => { open: boolean }
    openSchedule: (flagId: number) => { flagId: number }
    closeSchedule: () => { value: true }
    createRelease: (name: string, description: string) => { name: string; description: string }
    updateRelease: (id: string, changes: PatchedWriteReleaseApi) => { id: string; changes: PatchedWriteReleaseApi }
    linkFlag: (id: string, flagId: number) => { id: string; flagId: number }
    unlinkFlag: (id: string, flagId: number) => { id: string; flagId: number }
}

type releaseLogicType = MakeLogicType<ReleaseLogicValues, ReleaseLogicActions>

function results<T>(response: { results?: T[] } | T[]): T[] {
    return Array.isArray(response) ? response : (response.results ?? [])
}

export const releaseLogic = kea<releaseLogicType>([
    path(['products', 'release', 'frontend', 'releaseLogic']),
    connect(() => ({
        values: [projectLogic, ['currentProjectId'], userLogic, ['user']],
    })),
    actions({
        setSearch: (search: string) => ({ search }),
        setStageFilter: (stage: ReleaseStage | null) => ({ stage }),
        setDecisionOnly: (decisionOnly: boolean) => ({ decisionOnly }),
        setNewReleaseOpen: (open: boolean) => ({ open }),
        openSchedule: (flagId: number) => ({ flagId }),
        closeSchedule: true,
        createRelease: (name: string, description: string) => ({ name, description }),
        updateRelease: (id: string, changes: PatchedWriteReleaseApi) => ({ id, changes }),
        linkFlag: (id: string, flagId: number) => ({ id, flagId }),
        unlinkFlag: (id: string, flagId: number) => ({ id, flagId }),
    }),
    loaders(({ values }) => ({
        releases: [
            [] as ReleaseDTOApi[],
            {
                loadReleases: async () => results(await releasesList(String(values.currentProjectId))),
            },
        ],
        flags: [
            [] as FeatureFlagApi[],
            {
                loadFlags: async () => results(await featureFlagsList(String(values.currentProjectId), { limit: 500 })),
            },
        ],
        experiments: [
            [] as ExperimentBasicApi[],
            {
                loadExperiments: async () =>
                    results(await experimentsList(String(values.currentProjectId), { limit: 500 })).filter(
                        (experiment) => !experiment.archived
                    ),
            },
        ],
        earlyAccessFeatures: [
            [] as EarlyAccessFeatureApi[],
            {
                loadEarlyAccessFeatures: async () =>
                    results(await earlyAccessFeatureList(String(values.currentProjectId), { limit: 500 })),
            },
        ],
        scheduledChanges: [
            [] as ScheduledChangeApi[],
            {
                loadScheduledChanges: async () =>
                    results(await scheduledChangesList(String(values.currentProjectId), { limit: 500 })),
            },
        ],
    })),
    reducers({
        search: ['', { setSearch: (_, { search }) => search }],
        stageFilter: [null as ReleaseStage | null, { setStageFilter: (_, { stage }) => stage }],
        decisionOnly: [false, { setDecisionOnly: (_, { decisionOnly }) => decisionOnly }],
        newReleaseOpen: [false, { setNewReleaseOpen: (_, { open }) => open }],
        scheduleFlagId: [
            null as number | null,
            {
                openSchedule: (_, { flagId }) => flagId,
                closeSchedule: () => null,
            },
        ],
    }),
    selectors({
        dataLoading: [
            (s) => [s.releasesLoading, s.flagsLoading, s.experimentsLoading, s.flags],
            (releasesLoading, flagsLoading, experimentsLoading, flags): boolean =>
                releasesLoading || experimentsLoading || (flagsLoading && !flags.length),
        ],
        rows: [
            (s) => [s.releases, s.flags, s.experiments, s.earlyAccessFeatures, s.scheduledChanges, s.dataLoading],
            (
                releases: ReleaseDTOApi[],
                flags: FeatureFlagApi[],
                experiments: ExperimentBasicApi[],
                earlyAccessFeatures: EarlyAccessFeatureApi[],
                scheduledChanges: ScheduledChangeApi[],
                dataLoading: boolean
            ): ReleaseRow[] =>
                dataLoading && !flags.length
                    ? []
                    : releases.map((release) =>
                          buildReleaseRow(release, flags, experiments, earlyAccessFeatures, scheduledChanges)
                      ),
        ],
        filteredRows: [
            (s) => [s.rows, s.search, s.stageFilter, s.decisionOnly],
            (
                rows: ReleaseRow[],
                search: string,
                stageFilter: ReleaseStage | null,
                decisionOnly: boolean
            ): ReleaseRow[] => {
                const query = search.trim().toLowerCase()
                return rows.filter(
                    (row) =>
                        (!stageFilter || row.stage === stageFilter) &&
                        (!decisionOnly || row.needsDecision) &&
                        (!query ||
                            row.name.toLowerCase().includes(query) ||
                            row.flags.some((flag) => flag.key.toLowerCase().includes(query)))
                )
            },
        ],
        decisionRows: [(s) => [s.rows], (rows: ReleaseRow[]): ReleaseRow[] => rows.filter((row) => row.needsDecision)],
    }),
    listeners(({ actions, values }) => ({
        createRelease: async ({ name, description }) => {
            const release = await releasesCreate(String(values.currentProjectId), {
                name,
                description,
                owner_id: values.user?.id ?? null,
                feature_flag_ids: [],
            })
            actions.setNewReleaseOpen(false)
            actions.loadReleases()
            router.actions.push(urls.release(release.id))
        },
        updateRelease: async ({ id, changes }) => {
            await releasesPartialUpdate(String(values.currentProjectId), id, changes)
            actions.loadReleases()
        },
        linkFlag: async ({ id, flagId }) => {
            const release = values.releases.find((item) => item.id === id)
            if (!release || release.feature_flag_ids.includes(flagId)) {
                return
            }
            actions.updateRelease(id, { feature_flag_ids: [...release.feature_flag_ids, flagId] })
            lemonToast.success('Flag linked to the release')
        },
        unlinkFlag: async ({ id, flagId }) => {
            const release = values.releases.find((item) => item.id === id)
            if (release) {
                actions.updateRelease(id, {
                    feature_flag_ids: release.feature_flag_ids.filter((item) => item !== flagId),
                })
            }
        },
        closeSchedule: () => {
            actions.loadScheduledChanges()
            actions.loadFlags()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadReleases()
        actions.loadFlags()
        actions.loadExperiments()
        actions.loadEarlyAccessFeatures()
        actions.loadScheduledChanges()
    }),
])
