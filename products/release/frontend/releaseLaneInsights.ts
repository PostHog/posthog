import { ExperimentQueryResponse, HogQLQuery, NodeKind } from '~/queries/schema/schema-general'
import { ExperimentVariantResult, getChanceToWin } from '~/scenes/experiments/MetricsView/shared/utils'

export interface ErrorSplit {
    label: string
    users: number
    errored: number
}

export interface VariantOutcome {
    key: string
    change: number | null
    chanceToWin: number | null
    significant: boolean
}

export interface SurveyRating {
    question: string
    average: number
    answers: number
    scale: number
}

export type LaneInsights =
    | { kind: 'flag'; errors: ErrorSplit[]; health: { status: string; reason: string } | null }
    | {
          kind: 'experiment'
          metricName: string | null
          goal: 'increase' | 'decrease' | undefined
          outcomes: VariantOutcome[]
          findings: string[]
          errors: ErrorSplit[]
      }
    | { kind: 'survey'; rating: SurveyRating | null; latest: string[] }
    | { kind: 'early_access'; optedIn: number }

export interface SurveyQuestion {
    id?: string
    type?: string
    question?: string
    scale?: number
}

const MIN_USERS_FOR_ERRORS = 20

export function errorSplitQuery(flagKey: string): HogQLQuery {
    return {
        kind: NodeKind.HogQLQuery,
        query: `SELECT toString(properties[{prop}]) AS value, uniq(person_id) AS users, uniqIf(person_id, event = '$exception') AS errored
            FROM events
            WHERE event IN ('$exception', '$pageview', '$screen') AND timestamp >= now() - INTERVAL 7 DAY
                AND toString(properties[{prop}]) NOT IN ('', 'null')
            GROUP BY value ORDER BY users DESC LIMIT 6`,
        values: { prop: `$feature/${flagKey}` },
    }
}

export function parseErrorSplit(rows: unknown[][]): ErrorSplit[] {
    return rows
        .filter(([value]) => value !== null && value !== undefined && value !== '')
        .map(([value, users, errored]) => ({
            label: value === 'true' ? 'With the feature' : value === 'false' ? 'Without it' : String(value),
            users: Number(users),
            errored: Number(errored),
        }))
        .filter((item) => item.users > 0)
}

export function errorRate(split: ErrorSplit): number {
    return split.users ? split.errored / split.users : 0
}

export function errorsLookWorse(errors: ErrorSplit[]): ErrorSplit | null {
    const control = errors.find((item) => item.label === 'Without it' || item.label === 'control')
    if (!control || control.users < MIN_USERS_FOR_ERRORS) {
        return null
    }
    const worst = errors
        .filter((item) => item !== control && item.users >= MIN_USERS_FOR_ERRORS)
        .reduce<ErrorSplit | null>((max, item) => (!max || errorRate(item) > errorRate(max) ? item : max), null)
    return worst && errorRate(worst) > errorRate(control) * 1.2 && worst.errored >= 3 ? worst : null
}

function mean(result: { sum: number; number_of_samples: number }): number | null {
    return result.number_of_samples ? result.sum / result.number_of_samples : null
}

export function variantOutcomes(
    response: Pick<ExperimentQueryResponse, 'baseline' | 'variant_results'>,
    goal: 'increase' | 'decrease' | undefined
): VariantOutcome[] {
    const baseline = response.baseline ? mean(response.baseline) : null
    return (response.variant_results ?? []).map((variant) => {
        const value = mean(variant)
        return {
            key: variant.key,
            change: baseline && value !== null ? (value - baseline) / baseline : null,
            chanceToWin: getChanceToWin(variant as ExperimentVariantResult, goal) ?? null,
            significant: !!variant.significant,
        }
    })
}

export function leadingOutcome(outcomes: VariantOutcome[]): VariantOutcome | null {
    return outcomes.reduce<VariantOutcome | null>(
        (best, outcome) =>
            !best || (outcome.chanceToWin ?? outcome.change ?? 0) > (best.chanceToWin ?? best.change ?? 0)
                ? outcome
                : best,
        null
    )
}

function responseProperties(question: SurveyQuestion, index: number): [string, string] {
    const byIndex = index === 0 ? '$survey_response' : `$survey_response_${index}`
    return [question.id ? `$survey_response_${question.id}` : byIndex, byIndex]
}

export function surveyQueries(
    surveyId: string,
    questions: SurveyQuestion[]
): { rating: HogQLQuery | null; latest: HogQLQuery | null; ratingQuestion: SurveyQuestion | null } {
    const ratingIndex = questions.findIndex((question) => question.type === 'rating')
    const openIndex = questions.findIndex((question) => question.type === 'open')
    const answer = (index: number): string =>
        `coalesce(nullIf(toString(properties[{byId${index}}]), ''), nullIf(toString(properties[{byIndex${index}}]), ''))`
    const values = (index: number): Record<string, string> => {
        const [byId, byIndex] = responseProperties(questions[index], index)
        return { survey: surveyId, [`byId${index}`]: byId, [`byIndex${index}`]: byIndex }
    }
    return {
        ratingQuestion: ratingIndex >= 0 ? questions[ratingIndex] : null,
        rating:
            ratingIndex >= 0
                ? {
                      kind: NodeKind.HogQLQuery,
                      query: `SELECT avg(toFloatOrNull(${answer(ratingIndex)})), countIf(${answer(ratingIndex)} IS NOT NULL)
                          FROM events WHERE event = 'survey sent' AND properties.$survey_id = {survey}`,
                      values: values(ratingIndex),
                  }
                : null,
        latest:
            openIndex >= 0
                ? {
                      kind: NodeKind.HogQLQuery,
                      query: `SELECT ${answer(openIndex)} AS answer
                          FROM events WHERE event = 'survey sent' AND properties.$survey_id = {survey} AND answer IS NOT NULL
                          ORDER BY timestamp DESC LIMIT 3`,
                      values: values(openIndex),
                  }
                : null,
    }
}

export function enrollmentQuery(flagKey: string): HogQLQuery {
    return {
        kind: NodeKind.HogQLQuery,
        query: `SELECT countIf(state = 'true') FROM (
                SELECT person_id, argMax(toString(properties.$feature_enrollment), timestamp) AS state
                FROM events WHERE event = '$feature_enrollment_update' AND properties.$feature_flag = {flag}
                GROUP BY person_id
            )`,
        values: { flag: flagKey },
    }
}
