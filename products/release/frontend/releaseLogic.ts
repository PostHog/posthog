import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

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
import type { PatchedUpdateReleaseApi, ReleaseDTOApi } from './generated/api.schemas'
import { ReleaseRow, ReleaseStage, buildReleaseRow } from './releaseUtils'

interface ReleaseLogicValues {
    currentProjectId: number | null
    user: UserType | null
    releases: ReleaseDTOApi[]
    releasesLoading: boolean
    flags: FeatureFlagApi[]
    flagsLoading: boolean
    experiments: ExperimentBasicApi[]
    experimentsLoading: boolean
    earlyAccessFeatures: EarlyAccessFeatureApi[]
    scheduledChanges: ScheduledChangeApi[]
    search: string
    stageFilter: ReleaseStage | null
    decisionOnly: boolean
    newReleaseOpen: boolean
    creatingRelease: boolean
    loadFailed: boolean
    scheduleFlagId: number | null
    dataLoading: boolean
    activeFlags: FeatureFlagApi[]
    rows: ReleaseRow[]
    filteredRows: ReleaseRow[]
    decisionRows: ReleaseRow[]
}

interface ReleaseLogicActions {
    reload: (force?: boolean) => { force: boolean }
    loadReleases: () => void
    loadReleasesFailure: (error: string) => { error: string }
    setReleaseLocally: (
        id: string,
        changes: PatchedUpdateReleaseApi
    ) => { id: string; changes: PatchedUpdateReleaseApi }
    loadFlags: () => void
    loadFlagsFailure: (error: string) => { error: string }
    loadExperiments: () => void
    loadExperimentsFailure: (error: string) => { error: string }
    loadEarlyAccessFeatures: () => void
    loadEarlyAccessFeaturesFailure: (error: string) => { error: string }
    loadScheduledChanges: () => void
    loadScheduledChangesFailure: (error: string) => { error: string }
    setSearch: (search: string) => { search: string }
    setStageFilter: (stage: ReleaseStage | null) => { stage: ReleaseStage | null }
    setDecisionOnly: (decisionOnly: boolean) => { decisionOnly: boolean }
    setNewReleaseOpen: (open: boolean) => { open: boolean }
    openSchedule: (flagId: number) => { flagId: number }
    closeSchedule: () => { value: true }
    createRelease: (name: string, description: string) => { name: string; description: string }
    createReleaseDone: () => { value: true }
    updateRelease: (
        id: string,
        changes: PatchedUpdateReleaseApi,
        successMessage?: string
    ) => { id: string; changes: PatchedUpdateReleaseApi; successMessage?: string }
    linkFlag: (id: string, flagId: number) => { id: string; flagId: number }
    unlinkFlag: (id: string, flagId: number) => { id: string; flagId: number }
}

type releaseLogicType = MakeLogicType<ReleaseLogicValues, ReleaseLogicActions>

const PAGE_SIZE = 500
const RELOAD_WINDOW_MS = 2000

type ListPage<T> = { results?: T[]; next?: string | null } | T[]

async function allPages<T>(fetchPage: (offset: number) => Promise<ListPage<T>>): Promise<T[]> {
    const items: T[] = []
    for (;;) {
        const page = await fetchPage(items.length)
        if (Array.isArray(page)) {
            return page
        }
        const results = page.results ?? []
        items.push(...results)
        if (!page.next || !results.length) {
            return items
        }
    }
}

export const releaseLogic = kea<releaseLogicType>([
    path(['products', 'release', 'frontend', 'releaseLogic']),
    connect(() => ({
        values: [projectLogic, ['currentProjectId'], userLogic, ['user']],
    })),
    actions({
        reload: (force?: boolean) => ({ force: !!force }),
        setSearch: (search: string) => ({ search }),
        setStageFilter: (stage: ReleaseStage | null) => ({ stage }),
        setDecisionOnly: (decisionOnly: boolean) => ({ decisionOnly }),
        setNewReleaseOpen: (open: boolean) => ({ open }),
        openSchedule: (flagId: number) => ({ flagId }),
        closeSchedule: true,
        createRelease: (name: string, description: string) => ({ name, description }),
        createReleaseDone: true,
        updateRelease: (id: string, changes: PatchedUpdateReleaseApi, successMessage?: string) => ({
            id,
            changes,
            successMessage,
        }),
        linkFlag: (id: string, flagId: number) => ({ id, flagId }),
        unlinkFlag: (id: string, flagId: number) => ({ id, flagId }),
    }),
    loaders(({ values }) => ({
        releases: [
            [] as ReleaseDTOApi[],
            {
                loadReleases: async () =>
                    allPages((offset) => releasesList(String(values.currentProjectId), { limit: PAGE_SIZE, offset })),
                setReleaseLocally: ({ id, changes }) =>
                    values.releases.map((release) =>
                        release.id === id
                            ? {
                                  ...release,
                                  name: changes.name ?? release.name,
                                  description: changes.description ?? release.description,
                                  feature_flag_ids: changes.feature_flag_ids ?? release.feature_flag_ids,
                              }
                            : release
                    ),
            },
        ],
        flags: [
            [] as FeatureFlagApi[],
            {
                loadFlags: async () => {
                    const projectId = String(values.currentProjectId)
                    const [active, archived] = await Promise.all([
                        allPages((offset) => featureFlagsList(projectId, { limit: PAGE_SIZE, offset })),
                        allPages((offset) =>
                            featureFlagsList(projectId, { archived: 'true', limit: PAGE_SIZE, offset })
                        ),
                    ])
                    const seen = new Set(active.map((flag) => flag.id))
                    return [...active, ...archived.filter((flag) => !seen.has(flag.id))]
                },
            },
        ],
        experiments: [
            [] as ExperimentBasicApi[],
            {
                loadExperiments: async () =>
                    (
                        await allPages((offset) =>
                            experimentsList(String(values.currentProjectId), { limit: PAGE_SIZE, offset })
                        )
                    ).filter((experiment) => !experiment.archived),
            },
        ],
        earlyAccessFeatures: [
            [] as EarlyAccessFeatureApi[],
            {
                loadEarlyAccessFeatures: async () =>
                    allPages((offset) =>
                        earlyAccessFeatureList(String(values.currentProjectId), { limit: PAGE_SIZE, offset })
                    ),
            },
        ],
        scheduledChanges: [
            [] as ScheduledChangeApi[],
            {
                loadScheduledChanges: async () =>
                    allPages((offset) =>
                        scheduledChangesList(String(values.currentProjectId), { limit: PAGE_SIZE, offset })
                    ),
            },
        ],
    })),
    reducers({
        search: ['', { setSearch: (_, { search }) => search }],
        stageFilter: [null as ReleaseStage | null, { setStageFilter: (_, { stage }) => stage }],
        decisionOnly: [false, { setDecisionOnly: (_, { decisionOnly }) => decisionOnly }],
        newReleaseOpen: [false, { setNewReleaseOpen: (_, { open }) => open }],
        creatingRelease: [false, { createRelease: () => true, createReleaseDone: () => false }],
        loadFailed: [
            false,
            {
                reload: () => false,
                loadReleasesFailure: () => true,
                loadFlagsFailure: () => true,
                loadExperimentsFailure: () => true,
                loadEarlyAccessFeaturesFailure: () => true,
                loadScheduledChangesFailure: () => true,
            },
        ],
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
            (releasesLoading: boolean, flagsLoading: boolean, experimentsLoading: boolean, flags: FeatureFlagApi[]) =>
                releasesLoading || experimentsLoading || (flagsLoading && !flags.length),
        ],
        activeFlags: [(s) => [s.flags], (flags: FeatureFlagApi[]) => flags.filter((flag) => !flag.archived)],
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
            (rows: ReleaseRow[], search: string, stageFilter: ReleaseStage | null, decisionOnly: boolean) => {
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
        decisionRows: [(s) => [s.rows], (rows: ReleaseRow[]) => rows.filter((row) => row.needsDecision)],
    }),
    listeners(({ actions, values, cache }) => ({
        reload: ({ force }) => {
            const now = Date.now()
            if (!force && cache.lastReloadAt && now - cache.lastReloadAt < RELOAD_WINDOW_MS) {
                return
            }
            cache.lastReloadAt = now
            actions.loadReleases()
            actions.loadFlags()
            actions.loadExperiments()
            actions.loadEarlyAccessFeatures()
            actions.loadScheduledChanges()
        },
        createRelease: async ({ name, description }) => {
            try {
                const release = await releasesCreate(String(values.currentProjectId), {
                    name,
                    description,
                    owner_id: values.user?.id ?? null,
                    feature_flag_ids: [],
                })
                actions.setNewReleaseOpen(false)
                actions.loadReleases()
                router.actions.push(urls.release(release.id))
            } catch {
                lemonToast.error('The release could not be created. Try again.')
            } finally {
                actions.createReleaseDone()
            }
        },
        updateRelease: async ({ id, changes, successMessage }) => {
            actions.setReleaseLocally(id, changes)
            const previous: Promise<void> = cache.saving ?? Promise.resolve()
            cache.saving = previous.then(async () => {
                try {
                    await releasesPartialUpdate(String(values.currentProjectId), id, changes)
                    if (successMessage) {
                        lemonToast.success(successMessage)
                    }
                    if (changes.owner_id !== undefined) {
                        actions.loadReleases()
                    }
                } catch {
                    lemonToast.error('The change could not be saved. Try again.')
                    actions.loadReleases()
                }
            })
            await cache.saving
        },
        linkFlag: ({ id, flagId }) => {
            const release = values.releases.find((item) => item.id === id)
            if (release && !release.feature_flag_ids.includes(flagId)) {
                actions.updateRelease(
                    id,
                    { feature_flag_ids: [...release.feature_flag_ids, flagId] },
                    'Flag linked to the release'
                )
            }
        },
        unlinkFlag: ({ id, flagId }) => {
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
    urlToAction(({ actions }) => ({
        [urls.releases()]: () => actions.reload(),
        [urls.releaseList()]: () => actions.reload(),
        [urls.release(':id')]: () => actions.reload(),
    })),
    afterMount(({ actions }) => {
        actions.reload()
    }),
])
