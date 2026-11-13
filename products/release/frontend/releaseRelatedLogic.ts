import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { hogql } from 'lib/utils/hogql'
import { urls } from 'scenes/urls'

import { surveysCreate, surveysList } from 'products/surveys/frontend/generated/api'
import type { SurveyApi } from 'products/surveys/frontend/generated/api.schemas'

import type { ReleaseDTOApi } from './generated/api.schemas'
import { releaseLogic } from './releaseLogic'
import { TrackRelated, relatedFor } from './releaseTracks'
import { ReleaseRow, nameTokens } from './releaseUtils'

export interface RelatedSurvey {
    id: string
    name: string
    createdAt: string
    startDate: string | null
    endDate: string | null
    linkedFlagId: number | null
    archived: boolean
}

export interface RelatedInsight {
    id: number
    shortId: string
    name: string
    createdAt: string
    lastModifiedAt: string | null
}

export type RelatedKind = 'survey' | 'insight'

export interface RelatedSuggestion {
    key: string
    kind: RelatedKind
    id: string
    label: string
    reason: string
    detected: boolean
}

export interface RelatedSuggestions {
    releaseId: string
    items: RelatedSuggestion[]
    surveys: RelatedSurvey[]
    insights: RelatedInsight[]
}

export interface RelatedSearch {
    surveys: RelatedSurvey[]
    insights: RelatedInsight[]
}

const NO_SEARCH: RelatedSearch = { surveys: [], insights: [] }

interface ReleaseRelatedLogicValues {
    currentProjectId: number | null
    releases: ReleaseDTOApi[]
    linkedSurveys: Record<string, RelatedSurvey>
    linkedSurveysLoading: boolean
    linkedInsights: Record<number, RelatedInsight>
    linkedInsightsLoading: boolean
    relatedSuggestions: RelatedSuggestions | null
    relatedSuggestionsLoading: boolean
    relatedSearch: RelatedSearch
    relatedSearchLoading: boolean
    dismissed: Record<string, true>
    surveysById: Record<string, RelatedSurvey>
    insightsById: Record<number, RelatedInsight>
    relatedByRelease: Record<string, TrackRelated>
}

interface ReleaseRelatedLogicActions {
    loadLinkedSurveys: () => void
    loadLinkedSurveysSuccess: (linkedSurveys: Record<string, RelatedSurvey>) => {
        linkedSurveys: Record<string, RelatedSurvey>
    }
    loadLinkedSurveysFailure: (error: string) => { error: string }
    loadLinkedInsights: () => void
    loadLinkedInsightsSuccess: (linkedInsights: Record<number, RelatedInsight>) => {
        linkedInsights: Record<number, RelatedInsight>
    }
    loadLinkedInsightsFailure: (error: string) => { error: string }
    loadRelatedSuggestions: (row: ReleaseRow) => ReleaseRow
    loadRelatedSuggestionsSuccess: (relatedSuggestions: RelatedSuggestions | null) => {
        relatedSuggestions: RelatedSuggestions | null
    }
    loadRelatedSuggestionsFailure: (error: string) => { error: string }
    linkRelated: (releaseId: string, kind: RelatedKind, id: string) => { releaseId: string; kind: RelatedKind; id: string }
    unlinkRelated: (
        releaseId: string,
        kind: RelatedKind,
        id: string
    ) => { releaseId: string; kind: RelatedKind; id: string }
    searchRelated: (query: string) => string
    searchRelatedSuccess: (relatedSearch: RelatedSearch) => { relatedSearch: RelatedSearch }
    searchRelatedFailure: (error: string) => { error: string }
    dismissSuggestion: (key: string) => { key: string }
    createReleaseSurvey: (row: ReleaseRow) => { row: ReleaseRow }
    reloadReleases: () => void
}

type releaseRelatedLogicType = MakeLogicType<ReleaseRelatedLogicValues, ReleaseRelatedLogicActions>

const SUGGESTION_LIMIT = 6

function toSurvey(survey: SurveyApi): RelatedSurvey {
    return {
        id: survey.id,
        name: survey.name,
        createdAt: survey.created_at,
        startDate: survey.start_date ?? null,
        endDate: survey.end_date ?? null,
        linkedFlagId: survey.linked_flag_id ?? survey.linked_flag?.id ?? null,
        archived: !!survey.archived,
    }
}

function toInsight(row: unknown[]): RelatedInsight {
    const [id, shortId, name, createdAt, lastModifiedAt] = row as [number, string, string | null, string, string | null]
    return { id, shortId, name: name || 'Untitled insight', createdAt, lastModifiedAt }
}

async function queryInsights(query: ReturnType<typeof hogql>): Promise<RelatedInsight[]> {
    const response = await api.queryHogQL(query, { scene: 'Releases', productKey: 'feature_flags' })
    return (response.results ?? []).map(toInsight)
}

export const releaseRelatedLogic = kea<releaseRelatedLogicType>([
    path(['products', 'release', 'frontend', 'releaseRelatedLogic']),
    connect(() => ({
        values: [releaseLogic, ['currentProjectId', 'releases']],
        actions: [releaseLogic, ['loadReleasesSuccess as reloadReleases']],
    })),
    actions({
        linkRelated: (releaseId: string, kind: RelatedKind, id: string) => ({ releaseId, kind, id }),
        unlinkRelated: (releaseId: string, kind: RelatedKind, id: string) => ({ releaseId, kind, id }),
        dismissSuggestion: (key: string) => ({ key }),
        createReleaseSurvey: (row: ReleaseRow) => ({ row }),
    }),
    loaders(({ values }) => ({
        linkedSurveys: [
            {} as Record<string, RelatedSurvey>,
            {
                loadLinkedSurveys: async () => {
                    const ids = [...new Set(values.releases.flatMap((release) => release.survey_ids ?? []))]
                    if (!ids.length) {
                        return {}
                    }
                    const page = await surveysList(String(values.currentProjectId), { ids, limit: ids.length })
                    return Object.fromEntries(page.results.map((survey) => [survey.id, toSurvey(survey)]))
                },
            },
        ],
        linkedInsights: [
            {} as Record<number, RelatedInsight>,
            {
                loadLinkedInsights: async () => {
                    const ids = [...new Set(values.releases.flatMap((release) => release.insight_ids ?? []))]
                    if (!ids.length) {
                        return {}
                    }
                    const insights = await queryInsights(
                        hogql`SELECT id, short_id, name, created_at, last_modified_at FROM system.insights WHERE deleted = 0 AND id IN ${ids}`
                    )
                    return Object.fromEntries(insights.map((insight) => [insight.id, insight]))
                },
            },
        ],
        relatedSearch: [
            NO_SEARCH,
            {
                searchRelated: async (query: string, breakpoint) => {
                    await breakpoint(250)
                    const projectId = String(values.currentProjectId)
                    const term = query.trim()
                    const [surveys, insights] = await Promise.all([
                        surveysList(projectId, { search: term || undefined, archived: false, limit: 8 })
                            .then((page) => page.results.map(toSurvey))
                            .catch(() => [] as RelatedSurvey[]),
                        queryInsights(
                            hogql`SELECT id, short_id, name, created_at, last_modified_at FROM system.insights
                            WHERE deleted = 0 AND saved = 1 AND positionCaseInsensitive(coalesce(name, ''), ${term}) > 0
                            ORDER BY last_modified_at DESC LIMIT 8`
                        ).catch(() => [] as RelatedInsight[]),
                    ])
                    breakpoint()
                    return { surveys, insights }
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
                    const tokens = nameTokens(row.name).slice(0, 4)
                    const [flagSurveys, nameSurveys, flagInsights, nameInsights] = await Promise.all([
                        Promise.all(
                            row.flags.slice(0, 10).map((flag) =>
                                surveysList(projectId, { linked_flag_id: flag.id, archived: false, limit: 10 })
                                    .then((page) => page.results)
                                    .catch(() => [] as SurveyApi[])
                            )
                        ).then((pages) => pages.flat()),
                        Promise.all(
                            tokens.map((token) =>
                                surveysList(projectId, { search: token, archived: false, limit: 10 })
                                    .then((page) => page.results)
                                    .catch(() => [] as SurveyApi[])
                            )
                        ).then((pages) => pages.flat()),
                        flagKeys.length
                            ? queryInsights(
                                  hogql`SELECT id, short_id, name, created_at, last_modified_at FROM system.insights
                                  WHERE deleted = 0 AND saved = 1
                                  AND multiSearchAny(concat(toString(query), toString(filters)), ${flagKeys.map((key) => `$feature/${key}`)})
                                  ORDER BY last_modified_at DESC LIMIT 20`
                              ).catch(() => [] as RelatedInsight[])
                            : Promise.resolve([] as RelatedInsight[]),
                        tokens.length
                            ? queryInsights(
                                  hogql`SELECT id, short_id, name, created_at, last_modified_at FROM system.insights
                                  WHERE deleted = 0 AND saved = 1 AND multiSearchAnyCaseInsensitive(name, ${tokens})
                                  ORDER BY last_modified_at DESC LIMIT 20`
                              ).catch(() => [] as RelatedInsight[])
                            : Promise.resolve([] as RelatedInsight[]),
                    ])
                    breakpoint()
                    const wanted = new Set(tokens)
                    const overlap = (label: string): number =>
                        nameTokens(label).filter((token) => wanted.has(token)).length
                    const items = new Map<string, RelatedSuggestion>()
                    const flagKeyById = new Map(row.flags.map((flag) => [flag.id, flag.key]))
                    for (const survey of flagSurveys.map(toSurvey)) {
                        if (!linkedSurveys.has(survey.id) && !survey.archived) {
                            items.set(`survey:${survey.id}`, {
                                key: `survey:${survey.id}`,
                                kind: 'survey',
                                id: survey.id,
                                label: survey.name,
                                reason: `Shown to people who get ${flagKeyById.get(survey.linkedFlagId ?? -1) ?? 'a flag in this release'}`,
                                detected: true,
                            })
                        }
                    }
                    for (const insight of flagInsights) {
                        if (!linkedInsights.has(insight.id)) {
                            items.set(`insight:${insight.id}`, {
                                key: `insight:${insight.id}`,
                                kind: 'insight',
                                id: String(insight.id),
                                label: insight.name,
                                reason: 'Breaks down or filters by a flag in this release',
                                detected: true,
                            })
                        }
                    }
                    const named = [
                        ...nameSurveys.map(toSurvey).map((survey) => ({
                            key: `survey:${survey.id}`,
                            kind: 'survey' as const,
                            id: survey.id,
                            label: survey.name,
                            linked: linkedSurveys.has(survey.id) || survey.archived,
                        })),
                        ...nameInsights.map((insight) => ({
                            key: `insight:${insight.id}`,
                            kind: 'insight' as const,
                            id: String(insight.id),
                            label: insight.name,
                            linked: linkedInsights.has(insight.id),
                        })),
                    ]
                        .filter((item) => !item.linked && !items.has(item.key) && overlap(item.label) > 0)
                        .sort((a, b) => overlap(b.label) - overlap(a.label))
                        .slice(0, SUGGESTION_LIMIT)
                    for (const item of named) {
                        items.set(item.key, {
                            key: item.key,
                            kind: item.kind,
                            id: item.id,
                            label: item.label,
                            reason: 'Name matches this release',
                            detected: false,
                        })
                    }
                    return {
                        releaseId: row.id,
                        items: [...items.values()],
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
                dismissSuggestion: (state, { key }) => ({ ...state, [key]: true as const }),
                linkRelated: (state, { kind, id }) => ({ ...state, [`${kind}:${id}`]: true as const }),
            },
        ],
    }),
    selectors({
        surveysById: [
            (s) => [s.linkedSurveys, s.relatedSuggestions, s.relatedSearch],
            (linkedSurveys, relatedSuggestions, relatedSearch): Record<string, RelatedSurvey> => ({
                ...Object.fromEntries(
                    [...(relatedSuggestions?.surveys ?? []), ...relatedSearch.surveys].map((survey: RelatedSurvey) => [
                        survey.id,
                        survey,
                    ])
                ),
                ...linkedSurveys,
            }),
        ],
        insightsById: [
            (s) => [s.linkedInsights, s.relatedSuggestions, s.relatedSearch],
            (linkedInsights, relatedSuggestions, relatedSearch): Record<number, RelatedInsight> => ({
                ...Object.fromEntries(
                    [...(relatedSuggestions?.insights ?? []), ...relatedSearch.insights].map(
                        (insight: RelatedInsight) => [insight.id, insight]
                    )
                ),
                ...linkedInsights,
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
    listeners(({ actions, values }) => ({
        createReleaseSurvey: async ({ row }) => {
            const flag = row.flags[0]
            try {
                const survey = await surveysCreate(String(values.currentProjectId), {
                    name: `${row.name} feedback`,
                    type: 'popover',
                    linked_flag_id: flag?.id ?? null,
                    questions: [{ type: 'open', question: `What do you think of ${row.name}?` }],
                } as never)
                actions.linkRelated(row.id, 'survey', survey.id)
                router.actions.push(urls.survey(survey.id))
            } catch {
                lemonToast.error('Could not create the survey. Try again.')
            }
        },
        reloadReleases: () => {
            actions.loadLinkedSurveys()
            actions.loadLinkedInsights()
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
    afterMount(({ actions }) => {
        actions.loadLinkedSurveys()
        actions.loadLinkedInsights()
    }),
])
