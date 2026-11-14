import { MakeLogicType, actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { hogql } from 'lib/utils/hogql'
import { urls } from 'scenes/urls'

import { insightsList } from 'products/product_analytics/frontend/generated/api'
import { surveysCreate, surveysList } from 'products/surveys/frontend/generated/api'
import type { SurveyApi } from 'products/surveys/frontend/generated/api.schemas'

import type { ReleaseDTOApi } from './generated/api.schemas'
import { releaseLogic } from './releaseLogic'
import {
    INSIGHT_COLUMNS,
    RelatedInsight,
    RelatedKind,
    RelatedSuggestion,
    RelatedSurvey,
    fromLinkedInsight,
    fromLinkedSurvey,
    flagKeysPattern,
    rankRelatedSuggestions,
    toInsightRow,
    toSurvey,
} from './releaseRelated'
import { TrackRelated, relatedFor } from './releaseTracks'
import { ReleaseRow, nameTokens } from './releaseUtils'

export type { RelatedInsight, RelatedKind, RelatedSuggestion, RelatedSurvey } from './releaseRelated'

export interface RelatedSuggestions {
    releaseId: string
    failed: boolean
    items: RelatedSuggestion[]
    surveys: RelatedSurvey[]
    insights: RelatedInsight[]
}

export interface RelatedSearch {
    surveys: RelatedSurvey[]
    insights: RelatedInsight[]
    failed: boolean
}

const NO_SEARCH: RelatedSearch = { surveys: [], insights: [], failed: false }

interface ReleaseRelatedLogicValues {
    currentProjectId: number | null
    releases: ReleaseDTOApi[]
    linkedSurveys: Record<string, RelatedSurvey>
    linkedInsights: Record<number, RelatedInsight>
    relatedSuggestions: RelatedSuggestions | null
    relatedSuggestionsLoading: boolean
    relatedSearch: RelatedSearch
    relatedSearchLoading: boolean
    dismissed: Record<string, true>
    creatingSurvey: boolean
    lastRelatedSearch: string
    surveysById: Record<string, RelatedSurvey>
    insightsById: Record<number, RelatedInsight>
    relatedByRelease: Record<string, TrackRelated>
}

interface ReleaseRelatedLogicActions {
    loadRelatedSuggestions: (row: ReleaseRow) => ReleaseRow
    loadRelatedSuggestionsSuccess: (relatedSuggestions: RelatedSuggestions | null) => {
        relatedSuggestions: RelatedSuggestions | null
    }
    loadRelatedSuggestionsFailure: (error: string) => { error: string }
    linkRelated: (
        releaseId: string,
        kind: RelatedKind,
        id: string
    ) => { releaseId: string; kind: RelatedKind; id: string }
    unlinkRelated: (
        releaseId: string,
        kind: RelatedKind,
        id: string
    ) => { releaseId: string; kind: RelatedKind; id: string }
    searchRelated: (query: string) => string
    searchRelatedSuccess: (relatedSearch: RelatedSearch) => { relatedSearch: RelatedSearch }
    searchRelatedFailure: (error: string) => { error: string }
    dismissSuggestion: (releaseId: string, key: string) => { releaseId: string; key: string }
    createReleaseSurvey: (row: ReleaseRow) => { row: ReleaseRow }
    createReleaseSurveyDone: () => { done: true }
    rememberLinked: (
        surveys: RelatedSurvey[],
        insights: RelatedInsight[]
    ) => { surveys: RelatedSurvey[]; insights: RelatedInsight[] }
}

type releaseRelatedLogicType = MakeLogicType<ReleaseRelatedLogicValues, ReleaseRelatedLogicActions>

async function searchInsights(projectId: string, search: string, limit: number): Promise<RelatedInsight[]> {
    const page = await insightsList(projectId, { search: search || undefined, saved: true, basic: true, limit })
    return page.results.map((insight) => ({
        id: insight.id,
        shortId: insight.short_id,
        name: insight.name || insight.derived_name || 'Untitled insight',
        createdAt: insight.created_at ?? '',
        lastModifiedAt: insight.last_modified_at ?? null,
    }))
}

async function queryInsights(query: ReturnType<typeof hogql>): Promise<RelatedInsight[]> {
    const response = await api.queryHogQL(query, { scene: 'Releases', productKey: 'feature_flags' })
    return (response.results ?? []).map(toInsightRow)
}

export const releaseRelatedLogic = kea<releaseRelatedLogicType>([
    path(['products', 'release', 'frontend', 'releaseRelatedLogic']),
    connect(() => ({
        values: [releaseLogic, ['currentProjectId', 'releases']],
    })),
    actions({
        linkRelated: (releaseId: string, kind: RelatedKind, id: string) => ({ releaseId, kind, id }),
        unlinkRelated: (releaseId: string, kind: RelatedKind, id: string) => ({ releaseId, kind, id }),
        dismissSuggestion: (releaseId: string, key: string) => ({ releaseId, key }),
        createReleaseSurvey: (row: ReleaseRow) => ({ row }),
        createReleaseSurveyDone: () => ({ done: true as const }),
        rememberLinked: (surveys: RelatedSurvey[], insights: RelatedInsight[]) => ({ surveys, insights }),
    }),
    loaders(({ values }) => ({
        relatedSearch: [
            NO_SEARCH,
            {
                searchRelated: async (query: string, breakpoint) => {
                    await breakpoint(250)
                    const projectId = String(values.currentProjectId)
                    const term = query.trim()
                    let failed = false
                    const [surveys, insights] = await Promise.all([
                        surveysList(projectId, { search: term || undefined, archived: false, limit: 8 })
                            .then((page) => page.results.map(toSurvey))
                            .catch(() => {
                                failed = true
                                return [] as RelatedSurvey[]
                            }),
                        searchInsights(projectId, term, 8).catch(() => {
                            failed = true
                            return [] as RelatedInsight[]
                        }),
                    ])
                    breakpoint()
                    return { surveys, insights, failed }
                },
            },
        ],
        relatedSuggestions: [
            null as RelatedSuggestions | null,
            {
                loadRelatedSuggestions: async (row: ReleaseRow, breakpoint) => {
                    const projectId = String(values.currentProjectId)
                    const release = values.releases.find((item) => item.id === row.id)
                    const linkedSurveys = new Set(release?.survey_ids ?? [])
                    const linkedInsights = new Set(release?.insight_ids ?? [])
                    const flagKeys = row.flags.map((flag) => flag.key)
                    const firstFlagCreated = row.flags.map((flag) => flag.created_at).sort()[0] ?? row.createdAt
                    const tokens = nameTokens(row.name).slice(0, 4)
                    let failed = false
                    const fail = <T>(): T[] => {
                        failed = true
                        return []
                    }
                    const [flagSurveys, nameSurveys, flagInsights, nameInsights] = await Promise.all([
                        Promise.all(
                            row.flags.slice(0, 10).map((flag) =>
                                surveysList(projectId, { linked_flag_id: flag.id, archived: false, limit: 10 })
                                    .then((page) => page.results)
                                    .catch(() => fail<SurveyApi>())
                            )
                        ).then((pages) => pages.flat()),
                        Promise.all(
                            tokens.map((token) =>
                                surveysList(projectId, { search: token, archived: false, limit: 10 })
                                    .then((page) => page.results)
                                    .catch(() => fail<SurveyApi>())
                            )
                        ).then((pages) => pages.flat()),
                        flagKeys.length
                            ? queryInsights(
                                  hogql`SELECT ${INSIGHT_COLUMNS} FROM system.insights
                                  WHERE deleted = 0 AND saved = 1
                                  AND last_modified_at >= toDateTime(${firstFlagCreated})
                                  AND match(concat(toString(query), toString(filters)), ${flagKeysPattern(flagKeys)})
                                  ORDER BY last_modified_at DESC LIMIT 20`
                              ).catch(() => fail<RelatedInsight>())
                            : Promise.resolve([] as RelatedInsight[]),
                        Promise.all(
                            tokens.map((token) =>
                                searchInsights(projectId, token, 10).catch(() => fail<RelatedInsight>())
                            )
                        ).then((pages) => pages.flat()),
                    ])
                    breakpoint()
                    const items = rankRelatedSuggestions({
                        name: row.name,
                        flags: row.flags,
                        linkedSurveyIds: linkedSurveys,
                        linkedInsightIds: linkedInsights,
                        flagSurveys: flagSurveys.map(toSurvey),
                        flagInsights,
                        nameSurveys: nameSurveys.map(toSurvey),
                        nameInsights,
                    })
                    return {
                        releaseId: row.id,
                        failed,
                        items,
                        surveys: [...flagSurveys, ...nameSurveys].map(toSurvey),
                        insights: [...flagInsights, ...nameInsights],
                    }
                },
            },
        ],
    })),
    reducers({
        dismissed: [
            {} as Record<string, true>,
            {
                dismissSuggestion: (state, { releaseId, key }) => ({
                    ...state,
                    [`${releaseId}:${key}`]: true as const,
                }),
            },
        ],
        creatingSurvey: [
            false,
            {
                createReleaseSurvey: () => true,
                createReleaseSurveyDone: () => false,
            },
        ],
        lastRelatedSearch: [
            '',
            {
                searchRelated: (_, query) => query,
            },
        ],
        linkedSurveys: [
            {} as Record<string, RelatedSurvey>,
            {
                rememberLinked: (state, { surveys }) => ({
                    ...state,
                    ...Object.fromEntries(surveys.map((survey) => [survey.id, survey])),
                }),
            },
        ],
        linkedInsights: [
            {} as Record<number, RelatedInsight>,
            {
                rememberLinked: (state, { insights }) => ({
                    ...state,
                    ...Object.fromEntries(insights.map((insight) => [insight.id, insight])),
                }),
            },
        ],
    }),
    selectors({
        surveysById: [
            (s) => [s.linkedSurveys, s.relatedSuggestions, s.relatedSearch, s.releases],
            (linkedSurveys, relatedSuggestions, relatedSearch, releases): Record<string, RelatedSurvey> => ({
                ...Object.fromEntries(
                    [...(relatedSuggestions?.surveys ?? []), ...relatedSearch.surveys].map((survey: RelatedSurvey) => [
                        survey.id,
                        survey,
                    ])
                ),
                ...linkedSurveys,
                ...Object.fromEntries(
                    (releases as ReleaseDTOApi[])
                        .flatMap((release) => release.surveys ?? [])
                        .map((survey) => [survey.id, fromLinkedSurvey(survey)])
                ),
            }),
        ],
        insightsById: [
            (s) => [s.linkedInsights, s.relatedSuggestions, s.relatedSearch, s.releases],
            (linkedInsights, relatedSuggestions, relatedSearch, releases): Record<number, RelatedInsight> => ({
                ...Object.fromEntries(
                    [...(relatedSuggestions?.insights ?? []), ...relatedSearch.insights].map(
                        (insight: RelatedInsight) => [insight.id, insight]
                    )
                ),
                ...linkedInsights,
                ...Object.fromEntries(
                    (releases as ReleaseDTOApi[])
                        .flatMap((release) => release.insights ?? [])
                        .map((insight) => [insight.id, fromLinkedInsight(insight)])
                ),
            }),
        ],
        relatedByRelease: [
            (s) => [s.releases, s.surveysById, s.insightsById],
            (releases, surveysById, insightsById): Record<string, TrackRelated> =>
                Object.fromEntries(
                    (releases as ReleaseDTOApi[]).map((release) => [
                        release.id,
                        relatedFor(release, surveysById, insightsById),
                    ])
                ),
        ],
    }),
    listeners(({ actions, values, cache }) => ({
        createReleaseSurvey: async ({ row }) => {
            if (cache.creatingSurvey) {
                return
            }
            cache.creatingSurvey = true
            const flag = row.flags[0]
            const name = `${row.name} feedback`
            try {
                const survey = await surveysCreate(String(values.currentProjectId), {
                    name,
                    type: 'popover',
                    linked_flag_id: flag?.id ?? null,
                    questions: [{ type: 'open', question: `What do you think of ${row.name}?` }],
                } as never)
                actions.rememberLinked(
                    [
                        {
                            id: survey.id,
                            name,
                            createdAt: new Date().toISOString(),
                            startDate: null,
                            endDate: null,
                            linkedFlagId: flag?.id ?? null,
                            archived: false,
                        },
                    ],
                    []
                )
                const release = values.releases.find((item) => item.id === row.id)
                releaseLogic.actions.updateRelease(
                    row.id,
                    { survey_ids: [...(release?.survey_ids ?? []), survey.id] },
                    undefined,
                    { event: 'release item linked', properties: { release_id: row.id, kind: 'survey' } }
                )
                lemonToast.success('Survey created and linked to the release.', {
                    button: { label: 'Open survey', action: () => router.actions.push(urls.survey(survey.id)) },
                })
            } catch {
                lemonToast.error('Could not create the survey. Try again.')
            } finally {
                cache.creatingSurvey = false
                actions.createReleaseSurveyDone()
            }
        },
        linkRelated: ({ releaseId, kind, id }) => {
            const release = values.releases.find((item) => item.id === releaseId)
            if (!release) {
                return
            }
            const field = kind === 'survey' ? 'survey_ids' : 'insight_ids'
            const current = (release[field] ?? []) as (string | number)[]
            const value = kind === 'survey' ? id : Number(id)
            if (current.includes(value)) {
                return
            }
            const survey = kind === 'survey' ? values.surveysById[id] : undefined
            const insight = kind === 'insight' ? values.insightsById[Number(id)] : undefined
            actions.rememberLinked(survey ? [survey] : [], insight ? [insight] : [])
            releaseLogic.actions.updateRelease(
                releaseId,
                { [field]: [...current, value] },
                kind === 'survey' ? 'Linked the survey' : 'Linked the insight',
                { event: 'release item linked', properties: { release_id: releaseId, kind } }
            )
        },
        unlinkRelated: ({ releaseId, kind, id }) => {
            const release = values.releases.find((item) => item.id === releaseId)
            if (!release) {
                return
            }
            const field = kind === 'survey' ? 'survey_ids' : 'insight_ids'
            const current = (release[field] ?? []) as (string | number)[]
            const value = kind === 'survey' ? id : Number(id)
            releaseLogic.actions.updateRelease(
                releaseId,
                { [field]: current.filter((item) => item !== value) },
                undefined,
                { event: 'release item unlinked', properties: { release_id: releaseId, kind } }
            )
        },
    })),
])
