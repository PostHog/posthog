import { MakeLogicType, afterMount, connect, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import { performQuery } from '~/queries/query'
import { ExperimentMetric, NodeKind } from '~/queries/schema/schema-general'

import { experimentsHealthRetrieve, experimentsRetrieve } from 'products/experiments/frontend/generated/api'
import { featureFlagsStatusRetrieve } from 'products/feature_flags/frontend/generated/api'
import { surveysRetrieve } from 'products/surveys/frontend/generated/api'

import {
    LaneInsights,
    SurveyQuestion,
    enrollmentQuery,
    errorSplitQuery,
    parseErrorSplit,
    surveyQueries,
    variantOutcomes,
} from './releaseLaneInsights'
import { LaneUsage, UsageTarget, parseUsage, usageQueries } from './releaseLaneUsage'
import { releaseLogic } from './releaseLogic'

export interface ReleaseLaneUsageLogicProps {
    target: UsageTarget
    from: string
}

interface ReleaseLaneUsageLogicValues {
    currentProjectId: number | null
    usage: LaneUsage | null
    usageLoading: boolean
    insights: LaneInsights | null
    insightsLoading: boolean
}

interface ReleaseLaneUsageLogicActions {
    loadUsage: () => void
    loadUsageSuccess: (usage: LaneUsage | null) => { usage: LaneUsage | null }
    loadUsageFailure: (error: string) => { error: string }
    loadInsights: () => void
    loadInsightsSuccess: (insights: LaneInsights | null) => { insights: LaneInsights | null }
    loadInsightsFailure: (error: string) => { error: string }
}

type releaseLaneUsageLogicType = MakeLogicType<
    ReleaseLaneUsageLogicValues,
    ReleaseLaneUsageLogicActions,
    ReleaseLaneUsageLogicProps
>

export const releaseLaneUsageLogic = kea<releaseLaneUsageLogicType>([
    props({} as ReleaseLaneUsageLogicProps),
    key(({ target, from }) => `${target.kind}:${target.value}:${from}`),
    path((logicKey) => ['products', 'release', 'frontend', 'releaseLaneUsageLogic', logicKey]),
    connect(() => ({ values: [releaseLogic, ['currentProjectId']] })),
    loaders(({ props, values }) => ({
        usage: [
            null as LaneUsage | null,
            {
                loadUsage: async () => {
                    const queries = usageQueries(props.target, props.from)
                    const [daily, week, split] = await Promise.all([
                        performQuery(queries.daily),
                        performQuery(queries.week),
                        performQuery(queries.split),
                    ])
                    return parseUsage(
                        props.target.kind,
                        (daily.results ?? []) as unknown[][],
                        (week.results ?? []) as unknown[][],
                        (split.results ?? []) as unknown[][]
                    )
                },
            },
        ],
        insights: [
            null as LaneInsights | null,
            {
                loadInsights: async () => {
                    const projectId = String(values.currentProjectId)
                    const { target } = props
                    const rows = async (query: Parameters<typeof performQuery>[0]): Promise<unknown[][]> =>
                        (((await performQuery(query).catch(() => null)) as { results?: unknown[][] } | null)?.results ??
                            []) as unknown[][]
                    if (target.kind === 'flag') {
                        const [errors, health] = await Promise.all([
                            rows(errorSplitQuery(target.value)),
                            target.id
                                ? featureFlagsStatusRetrieve(projectId, target.id).catch(() => null)
                                : Promise.resolve(null),
                        ])
                        return {
                            kind: 'flag',
                            errors: parseErrorSplit(errors),
                            health: health ? { status: health.status, reason: health.reason } : null,
                        }
                    }
                    if (target.kind === 'experiment' && target.id) {
                        const experiment = await experimentsRetrieve(projectId, target.id).catch(() => null)
                        const metric = ((experiment?.metrics ?? []) as ExperimentMetric[])[0]
                        const [result, health, errors] = await Promise.all([
                            metric
                                ? performQuery({
                                      kind: NodeKind.ExperimentQuery,
                                      experiment_id: target.id,
                                      metric,
                                  }).catch(() => null)
                                : Promise.resolve(null),
                            experimentsHealthRetrieve(projectId, target.id).catch(() => null),
                            rows(errorSplitQuery(target.value)),
                        ])
                        const goal = metric && 'goal' in metric ? metric.goal : undefined
                        return {
                            kind: 'experiment',
                            metricName: metric ? metric.name || 'Primary metric' : null,
                            goal,
                            outcomes: result
                                ? variantOutcomes(result, goal).filter((outcome) => outcome.key !== 'control')
                                : [],
                            findings: (health?.findings ?? [])
                                .filter((finding) => finding.severity !== 'info')
                                .map((finding) => finding.title),
                            errors: parseErrorSplit(errors),
                        }
                    }
                    if (target.kind === 'survey') {
                        const survey = await surveysRetrieve(projectId, target.value).catch(() => null)
                        const queries = surveyQueries(target.value, (survey?.questions ?? []) as SurveyQuestion[])
                        const [rating, latest] = await Promise.all([
                            queries.rating ? rows(queries.rating) : Promise.resolve([]),
                            queries.latest ? rows(queries.latest) : Promise.resolve([]),
                        ])
                        const answers = Number(rating[0]?.[1] ?? 0)
                        return {
                            kind: 'survey',
                            rating:
                                queries.ratingQuestion && answers
                                    ? {
                                          question: queries.ratingQuestion.question ?? '',
                                          average: Number(rating[0]?.[0] ?? 0),
                                          answers,
                                          scale: queries.ratingQuestion.scale ?? 5,
                                      }
                                    : null,
                            latest: latest.map(([answer]) => String(answer)),
                        }
                    }
                    if (target.kind === 'early_access') {
                        const enrolled = await rows(enrollmentQuery(target.value))
                        return { kind: 'early_access', optedIn: Number(enrolled[0]?.[0] ?? 0) }
                    }
                    return null
                },
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadUsage()
        actions.loadInsights()
    }),
])
