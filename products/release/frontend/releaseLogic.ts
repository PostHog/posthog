import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { FeatureFlagsSet, featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { projectLogic } from 'scenes/projectLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { AccessControlLevel, AccessControlResourceType, type UserType } from '~/types'

import { earlyAccessFeatureList } from 'products/early_access_features/frontend/generated/api'
import type { EarlyAccessFeatureApi } from 'products/early_access_features/frontend/generated/api.schemas'
import { experimentsList } from 'products/experiments/frontend/generated/api'
import type { ExperimentBasicApi } from 'products/experiments/frontend/generated/api.schemas'
import { featureFlagsList, scheduledChangesList } from 'products/feature_flags/frontend/generated/api'
import type { FeatureFlagApi, ScheduledChangeApi } from 'products/feature_flags/frontend/generated/api.schemas'

import { releasesCreate, releasesList, releasesPartialUpdate } from './generated/api'
import type { PatchedUpdateReleaseApi, ReleaseDTOApi } from './generated/api.schemas'
import {
    ReleaseRow,
    ReleaseStage,
    ScheduleIndex,
    buildReleaseRow,
    composeReleaseIndex,
    indexEarlyAccess,
    indexExperiments,
    indexFlags,
    indexSchedules,
} from './releaseUtils'

interface ReleaseLogicValues {
    currentProjectId: number | null
    featureFlags: FeatureFlagsSet
    releasesEnabled: boolean
    user: UserType | null
    releases: ReleaseDTOApi[]
    releasesLoading: boolean
    flags: FeatureFlagApi[]
    flagsLoading: boolean
    flagsReady: boolean
    flagSearchResults: FeatureFlagApi[]
    flagSearchResultsLoading: boolean
    flagSearch: string
    flagSearchFailed: boolean
    flagCount: number
    experiments: ExperimentBasicApi[]
    experimentsLoading: boolean
    experimentCount: number
    earlyAccessFeatures: EarlyAccessFeatureApi[]
    earlyAccessCount: number
    scheduledChanges: ScheduledChangeApi[]
    search: string
    stageFilter: ReleaseStage | null
    decisionOnly: boolean
    newReleaseOpen: boolean
    creatingRelease: boolean
    loadFailed: boolean
    experimentsFailed: boolean
    earlyAccessFailed: boolean
    experimentsReady: boolean
    hiddenExperimentFlagIds: number[]
    hiddenEarlyAccessFlagIds: number[]
    resolvedFlagIds: number[]
    earlyAccessReady: boolean
    schedulesFailed: boolean
    partialLoadFailed: boolean
    scheduleFlagId: number | null
    dataLoading: boolean
    flagsById: Map<number, FeatureFlagApi>
    experimentsByFlagKey: Map<string, ExperimentBasicApi[]>
    earlyAccessByFlagKey: Map<string, EarlyAccessFeatureApi[]>
    scheduleIndex: ScheduleIndex
    canEditReleases: boolean
    rows: ReleaseRow[]
    filteredRows: ReleaseRow[]
    decisionRows: ReleaseRow[]
}

interface ReleaseLogicActions {
    reload: (force?: boolean) => { force: boolean }
    setFeatureFlags: (
        flags: string[],
        variants: Record<string, string | boolean>
    ) => { flags: string[]; variants: Record<string, string | boolean> }
    loadReleases: () => void
    loadReleasesFailure: (error: string) => { error: string }
    setReleaseLocally: (update: { id: string; changes: PatchedUpdateReleaseApi }) => {
        id: string
        changes: PatchedUpdateReleaseApi
    }
    loadFlags: () => void
    loadFlagsSuccess: (flags: FeatureFlagApi[]) => { flags: FeatureFlagApi[] }
    loadFlagsFailure: (error: string) => { error: string }
    loadReleasesSuccess: (releases: ReleaseDTOApi[]) => { releases: ReleaseDTOApi[] }
    searchFlags: (search: string) => string
    searchFlagsFailure: (error: string) => { error: string }
    loadFlagCount: () => void
    loadExperiments: () => void
    loadExperimentsSuccess: (experiments: ExperimentBasicApi[]) => { experiments: ExperimentBasicApi[] }
    loadExperimentsFailure: (error: string) => { error: string }
    loadExperimentCount: () => void
    setHiddenExperimentFlagIds: (flagIds: number[]) => { flagIds: number[] }
    setHiddenEarlyAccessFlagIds: (flagIds: number[]) => { flagIds: number[] }
    setResolvedFlagIds: (flagIds: number[]) => { flagIds: number[] }
    loadEarlyAccessFeatures: () => void
    loadEarlyAccessCount: () => void
    loadEarlyAccessFeaturesSuccess: (earlyAccessFeatures: EarlyAccessFeatureApi[]) => {
        earlyAccessFeatures: EarlyAccessFeatureApi[]
    }
    loadEarlyAccessFeaturesFailure: (error: string) => { error: string }
    loadScheduledChanges: () => void
    loadScheduledChangesSuccess: (scheduledChanges: ScheduledChangeApi[]) => {
        scheduledChanges: ScheduledChangeApi[]
    }
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
const FLAG_SEARCH_LIMIT = 50
const FLAG_FETCH_CONCURRENCY = 8
const ID_CHUNK = 100

type ListPage<T> = { results?: T[]; next?: string | null } | T[]

function inRequestedOrder<T, K>(items: T[], ids: K[], idOf: (item: T) => K): T[] {
    const position = new Map(ids.map((id, index) => [id, index]))
    return [...items].sort((a, b) => (position.get(idOf(a)) ?? 0) - (position.get(idOf(b)) ?? 0))
}

function chunk<T>(items: T[], size: number): T[][] {
    const chunks: T[][] = []
    for (let start = 0; start < items.length; start += size) {
        chunks.push(items.slice(start, start + size))
    }
    return chunks
}

function linkedFlagIds(releases: ReleaseDTOApi[]): number[] {
    return [...new Set(releases.flatMap((release) => release.feature_flag_ids))]
}

async function inBatches<T, R>(
    items: T[],
    fetch: (item: T) => Promise<R>,
    breakpoint: () => void
): Promise<PromiseSettledResult<R>[]> {
    const results: PromiseSettledResult<R>[] = []
    for (let start = 0; start < items.length; start += FLAG_FETCH_CONCURRENCY) {
        results.push(...(await Promise.allSettled(items.slice(start, start + FLAG_FETCH_CONCURRENCY).map(fetch))))
        breakpoint()
    }
    return results
}

function valuesOrThrow<R>(results: PromiseSettledResult<R>[]): R[] {
    return results.map((result) => {
        if (result.status === 'rejected') {
            throw result.reason
        }
        return result.value
    })
}

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
        values: [projectLogic, ['currentProjectId'], userLogic, ['user'], featureFlagLogic, ['featureFlags']],
        actions: [featureFlagLogic, ['setFeatureFlags']],
    })),
    actions({
        reload: (force?: boolean) => ({ force: !!force }),
        setHiddenExperimentFlagIds: (flagIds: number[]) => ({ flagIds }),
        setHiddenEarlyAccessFlagIds: (flagIds: number[]) => ({ flagIds }),
        setResolvedFlagIds: (flagIds: number[]) => ({ flagIds }),
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
    loaders(({ values, actions }) => ({
        releases: [
            [] as ReleaseDTOApi[],
            {
                loadReleases: async (_, breakpoint) => {
                    const releases = await allPages((offset) =>
                        releasesList(String(values.currentProjectId), { limit: PAGE_SIZE, offset })
                    )
                    breakpoint()
                    return releases
                },
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
                loadFlags: async (_, breakpoint) => {
                    const projectId = String(values.currentProjectId)
                    const ids = linkedFlagIds(values.releases)
                    const pages = valuesOrThrow(
                        await inBatches(
                            chunk(ids, ID_CHUNK),
                            (idChunk) =>
                                allPages((offset) =>
                                    featureFlagsList(projectId, { ids: idChunk.join(','), limit: PAGE_SIZE, offset })
                                ),
                            breakpoint
                        )
                    )
                    actions.setResolvedFlagIds(ids)
                    return inRequestedOrder(
                        pages.flat().filter((flag) => !flag.deleted),
                        ids,
                        (flag) => flag.id
                    )
                },
            },
        ],
        flagSearchResults: [
            [] as FeatureFlagApi[],
            {
                searchFlags: async (search: string, breakpoint) => {
                    await breakpoint(250)
                    const page = await featureFlagsList(String(values.currentProjectId), {
                        search: search || undefined,
                        limit: FLAG_SEARCH_LIMIT,
                    })
                    breakpoint()
                    return page.results ?? []
                },
            },
        ],
        flagCount: [
            0,
            {
                loadFlagCount: async () =>
                    (await featureFlagsList(String(values.currentProjectId), { limit: 1 })).count ?? 0,
            },
        ],
        experiments: [
            [] as ExperimentBasicApi[],
            {
                loadExperiments: async (_, breakpoint) => {
                    const projectId = String(values.currentProjectId)
                    const flagsWithExperiments = values.flags.filter((flag) => flag.experiment_set?.length)
                    const listFor = async (flagIds: number[], archived: boolean): Promise<ExperimentBasicApi[]> =>
                        valuesOrThrow(
                            await inBatches(
                                chunk(flagIds, ID_CHUNK),
                                (idChunk) =>
                                    allPages((offset) =>
                                        experimentsList(projectId, {
                                            feature_flag_ids: idChunk.join(','),
                                            archived,
                                            limit: PAGE_SIZE,
                                            offset,
                                        })
                                    ),
                                breakpoint
                            )
                        ).flat()
                    const active = await listFor(
                        flagsWithExperiments.map((flag) => flag.id),
                        false
                    )
                    const activeCount = new Map<string, number>()
                    for (const experiment of active) {
                        const key = experiment.feature_flag_key
                        activeCount.set(key, (activeCount.get(key) ?? 0) + 1)
                    }
                    const short = flagsWithExperiments.filter(
                        (flag) => (activeCount.get(flag.key) ?? 0) < flag.experiment_set.length
                    )
                    const experiments = [
                        ...active,
                        ...(await listFor(
                            short.map((flag) => flag.id),
                            true
                        )),
                    ]
                    const loadedIds = new Set(experiments.map((experiment) => experiment.id))
                    actions.setHiddenExperimentFlagIds(
                        flagsWithExperiments
                            .filter((flag) => flag.experiment_set.some((id) => !loadedIds.has(id)))
                            .map((flag) => flag.id)
                    )
                    return experiments
                },
            },
        ],
        experimentCount: [
            0,
            {
                loadExperimentCount: async () =>
                    (await experimentsList(String(values.currentProjectId), { limit: 1 })).count ?? 0,
            },
        ],
        earlyAccessFeatures: [
            [] as EarlyAccessFeatureApi[],
            {
                loadEarlyAccessFeatures: async (_, breakpoint) => {
                    const projectId = String(values.currentProjectId)
                    const ids = [
                        ...new Set(
                            values.flags.flatMap((flag) =>
                                ((flag.features as unknown as { id: string }[] | undefined) ?? []).map(
                                    (item) => item.id
                                )
                            )
                        ),
                    ]
                    const pages = valuesOrThrow(
                        await inBatches(
                            chunk(ids, ID_CHUNK),
                            (idChunk) =>
                                allPages((offset) =>
                                    earlyAccessFeatureList(projectId, {
                                        ids: idChunk.join(','),
                                        limit: PAGE_SIZE,
                                        offset,
                                    })
                                ),
                            breakpoint
                        )
                    )
                    const features = pages.flat()
                    const loadedIds = new Set(features.map((feature) => feature.id))
                    actions.setHiddenEarlyAccessFlagIds(
                        values.flags
                            .filter((flag) =>
                                ((flag.features as unknown as { id: string }[] | undefined) ?? []).some(
                                    (item) => !loadedIds.has(item.id)
                                )
                            )
                            .map((flag) => flag.id)
                    )
                    return inRequestedOrder(features, ids, (feature) => feature.id)
                },
            },
        ],
        earlyAccessCount: [
            0,
            {
                loadEarlyAccessCount: async () =>
                    (await earlyAccessFeatureList(String(values.currentProjectId), { limit: 1 })).count ?? 0,
            },
        ],
        scheduledChanges: [
            [] as ScheduledChangeApi[],
            {
                loadScheduledChanges: async (_, breakpoint) => {
                    const projectId = String(values.currentProjectId)
                    const pages = valuesOrThrow(
                        await inBatches(
                            chunk(linkedFlagIds(values.releases), ID_CHUNK),
                            (ids) =>
                                allPages((offset) =>
                                    scheduledChangesList(projectId, {
                                        model_name: 'FeatureFlag',
                                        record_ids: ids.join(','),
                                        limit: PAGE_SIZE,
                                        offset,
                                    })
                                ),
                            breakpoint
                        )
                    )
                    return pages.flat()
                },
            },
        ],
    })),
    reducers({
        search: ['', { setSearch: (_, { search }) => search }],
        stageFilter: [null as ReleaseStage | null, { setStageFilter: (_, { stage }) => stage }],
        decisionOnly: [false, { setDecisionOnly: (_, { decisionOnly }) => decisionOnly }],
        newReleaseOpen: [false, { setNewReleaseOpen: (_, { open }) => open }],
        creatingRelease: [false, { createRelease: () => true, createReleaseDone: () => false }],
        flagSearch: ['', { searchFlags: (_, search) => search }],
        flagSearchFailed: [false, { searchFlags: () => false, searchFlagsFailure: () => true }],
        flagsReady: [false, { loadFlagsSuccess: () => true, loadFlagsFailure: () => true }],
        experimentsReady: [false, { loadExperimentsSuccess: () => true }],
        hiddenExperimentFlagIds: [[] as number[], { setHiddenExperimentFlagIds: (_, { flagIds }) => flagIds }],
        hiddenEarlyAccessFlagIds: [[] as number[], { setHiddenEarlyAccessFlagIds: (_, { flagIds }) => flagIds }],
        resolvedFlagIds: [[] as number[], { setResolvedFlagIds: (_, { flagIds }) => flagIds }],
        earlyAccessReady: [false, { loadEarlyAccessFeaturesSuccess: () => true }],
        loadFailed: [
            false,
            {
                loadReleases: () => false,
                loadFlags: () => false,
                loadReleasesFailure: () => true,
                loadFlagsFailure: () => true,
            },
        ],
        experimentsFailed: [false, { loadExperiments: () => false, loadExperimentsFailure: () => true }],
        earlyAccessFailed: [
            false,
            { loadEarlyAccessFeatures: () => false, loadEarlyAccessFeaturesFailure: () => true },
        ],
        schedulesFailed: [false, { loadScheduledChanges: () => false, loadScheduledChangesFailure: () => true }],
        scheduleFlagId: [
            null as number | null,
            {
                openSchedule: (_, { flagId }) => flagId,
                closeSchedule: () => null,
            },
        ],
    }),
    selectors({
        releasesEnabled: [
            (s) => [s.featureFlags],
            (featureFlags: FeatureFlagsSet): boolean => !!featureFlags[FEATURE_FLAGS.RELEASES_AREA],
        ],
        canEditReleases: [
            () => [],
            (): boolean => userHasAccess(AccessControlResourceType.FeatureFlag, AccessControlLevel.Editor),
        ],
        partialLoadFailed: [
            (s) => [
                s.experimentsFailed,
                s.hiddenExperimentFlagIds,
                s.earlyAccessFailed,
                s.hiddenEarlyAccessFlagIds,
                s.schedulesFailed,
            ],
            (
                experimentsFailed: boolean,
                hiddenExperimentFlagIds: number[],
                earlyAccessFailed: boolean,
                hiddenEarlyAccessFlagIds: number[],
                schedulesFailed: boolean
            ) =>
                experimentsFailed ||
                hiddenExperimentFlagIds.length > 0 ||
                earlyAccessFailed ||
                hiddenEarlyAccessFlagIds.length > 0 ||
                schedulesFailed,
        ],
        dataLoading: [
            (s) => [s.releasesLoading, s.experimentsLoading, s.flagsReady, s.loadFailed],
            (releasesLoading: boolean, experimentsLoading: boolean, flagsReady: boolean, loadFailed: boolean) =>
                !loadFailed && (releasesLoading || experimentsLoading || !flagsReady),
        ],
        flagsById: [(s) => [s.flags], (flags: FeatureFlagApi[]) => indexFlags(flags)],
        experimentsByFlagKey: [
            (s) => [s.experiments],
            (experiments: ExperimentBasicApi[]) => indexExperiments(experiments),
        ],
        earlyAccessByFlagKey: [
            (s) => [s.earlyAccessFeatures],
            (earlyAccessFeatures: EarlyAccessFeatureApi[]) => indexEarlyAccess(earlyAccessFeatures),
        ],
        scheduleIndex: [
            (s) => [s.flags, s.scheduledChanges],
            (flags: FeatureFlagApi[], scheduledChanges: ScheduledChangeApi[]) =>
                indexSchedules(flags, scheduledChanges),
        ],
        rows: [
            (s) => [
                s.releases,
                s.flagsById,
                s.experimentsByFlagKey,
                s.earlyAccessByFlagKey,
                s.scheduleIndex,
                s.flagsReady,
                s.loadFailed,
                s.experimentsFailed,
                s.earlyAccessFailed,
                s.experimentsReady,
                s.hiddenExperimentFlagIds,
                s.hiddenEarlyAccessFlagIds,
                s.earlyAccessReady,
                s.resolvedFlagIds,
            ],
            (
                releases: ReleaseDTOApi[],
                flagsById: Map<number, FeatureFlagApi>,
                experimentsByFlagKey: Map<string, ExperimentBasicApi[]>,
                earlyAccessByFlagKey: Map<string, EarlyAccessFeatureApi[]>,
                scheduleIndex: ScheduleIndex,
                flagsReady: boolean,
                loadFailed: boolean,
                experimentsFailed: boolean,
                earlyAccessFailed: boolean,
                experimentsReady: boolean,
                hiddenExperimentFlagIds: number[],
                hiddenEarlyAccessFlagIds: number[],
                earlyAccessReady: boolean,
                resolvedFlagIds: number[]
            ): ReleaseRow[] => {
                if (!flagsReady || loadFailed) {
                    return []
                }
                const index = composeReleaseIndex(
                    { flagsById, experimentsByFlagKey, earlyAccessByFlagKey, schedules: scheduleIndex },
                    {
                        complete: experimentsReady && earlyAccessReady && !experimentsFailed && !earlyAccessFailed,
                        resolvedFlagIds,
                        unknownFlagIds: [...new Set([...hiddenExperimentFlagIds, ...hiddenEarlyAccessFlagIds])],
                    }
                )
                return releases.map((release) => buildReleaseRow(release, index))
            },
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
        setFeatureFlags: () => {
            if (values.releasesEnabled && !cache.lastReloadAt) {
                actions.reload()
            }
        },
        reload: ({ force }) => {
            if (!values.releasesEnabled) {
                return
            }
            const now = Date.now()
            if (!force && cache.lastReloadAt && now - cache.lastReloadAt < RELOAD_WINDOW_MS) {
                return
            }
            cache.lastReloadAt = now
            actions.loadReleases()
            actions.loadFlagCount()
            actions.loadExperimentCount()
            actions.loadEarlyAccessCount()
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
            actions.setReleaseLocally({ id, changes })
            cache.pendingSaves = (cache.pendingSaves ?? 0) + 1
            cache.pendingById = { ...cache.pendingById, [id]: (cache.pendingById?.[id] ?? 0) + 1 }
            const previous: Promise<void> = cache.saving ?? Promise.resolve()
            cache.saving = previous.then(async () => {
                try {
                    const saved = await releasesPartialUpdate(String(values.currentProjectId), id, changes)
                    if (cache.pendingById[id] === 1) {
                        actions.setReleaseLocally({
                            id,
                            changes: {
                                name: saved.name,
                                description: saved.description,
                                feature_flag_ids: saved.feature_flag_ids,
                            },
                        })
                    }
                    if (successMessage) {
                        lemonToast.success(successMessage)
                    }
                    if (changes.owner_id !== undefined) {
                        cache.refetchAfterSaves = true
                    }
                    if (changes.feature_flag_ids !== undefined) {
                        cache.relinkAfterSaves = true
                    }
                } catch {
                    lemonToast.error('The change could not be saved. Try again.')
                    cache.refetchAfterSaves = true
                } finally {
                    cache.pendingSaves -= 1
                    cache.pendingById[id] -= 1
                    if (cache.pendingSaves === 0) {
                        if (cache.refetchAfterSaves) {
                            actions.loadReleases()
                        } else if (cache.relinkAfterSaves) {
                            actions.loadFlags()
                            actions.loadScheduledChanges()
                        }
                        cache.refetchAfterSaves = false
                        cache.relinkAfterSaves = false
                    }
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
        loadFlagsSuccess: () => {
            actions.loadExperiments()
            actions.loadEarlyAccessFeatures()
        },
        loadReleasesSuccess: () => {
            actions.loadFlags()
            actions.loadScheduledChanges()
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
