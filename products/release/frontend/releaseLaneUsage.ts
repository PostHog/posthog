import { dayjs } from 'lib/dayjs'

import { HogQLQuery, NodeKind } from '~/queries/schema/schema-general'

import { Lane } from './releaseTracks'
import { ReleaseRow } from './releaseUtils'

export type UsageKind = 'flag' | 'experiment' | 'early_access' | 'survey'

export interface UsageTarget {
    kind: UsageKind
    value: string
    id?: number
}

export interface UsageDay {
    day: string
    users: number
    total: number
}

export interface UsageSplit {
    label: string
    users: number
}

export interface LaneUsage {
    days: UsageDay[]
    weekUsers: number
    weekTotal: number
    split: UsageSplit[]
}

const SOURCE: Record<UsageKind, { event: string; filter: string }> = {
    flag: { event: '$feature_flag_called', filter: 'properties.$feature_flag = {target}' },
    experiment: { event: '$feature_flag_called', filter: 'properties.$feature_flag = {target}' },
    early_access: { event: '$feature_enrollment_update', filter: 'properties.$feature_flag = {target}' },
    survey: { event: 'survey sent', filter: 'properties.$survey_id = {target}' },
}

export function usageTarget(lane: Lane, row: ReleaseRow): UsageTarget | null {
    if (lane.kind === 'flag') {
        return { kind: 'flag', value: lane.flag.key, id: lane.flag.id }
    }
    if (lane.kind === 'survey') {
        return { kind: 'survey', value: lane.survey.id }
    }
    if (lane.kind === 'experiment') {
        const experiment = row.experiments.find((item) => `experiment-${item.id}` === lane.key)
        return experiment?.feature_flag_key
            ? { kind: 'experiment', value: experiment.feature_flag_key, id: experiment.id }
            : null
    }
    if (lane.kind === 'early_access') {
        const key = row.earlyAccess.find((item) => `early-access-${item.id}` === lane.key)?.feature_flag?.key
        return key ? { kind: 'early_access', value: key } : null
    }
    return null
}

function hogql(query: string, values: Record<string, string>): HogQLQuery {
    return { kind: NodeKind.HogQLQuery, query, values }
}

export function usageQueries(
    target: UsageTarget,
    from: string
): { daily: HogQLQuery; week: HogQLQuery; split: HogQLQuery } {
    const { event, filter } = SOURCE[target.kind]
    const values = { target: target.value, event, from: dayjs(from).utc().format('YYYY-MM-DD HH:mm:ss') }
    const where = `event = {event} AND ${filter}`
    const split =
        target.kind === 'survey'
            ? hogql(
                  `SELECT uniqIf(person_id, event = 'survey shown'), uniqIf(person_id, event = 'survey sent'), uniqIf(person_id, event = 'survey dismissed')
                  FROM events WHERE event IN ('survey shown', 'survey sent', 'survey dismissed') AND ${filter} AND timestamp >= toDateTime({from})`,
                  values
              )
            : hogql(
                  `SELECT toString(properties.${target.kind === 'early_access' ? '$feature_enrollment' : '$feature_flag_response'}) AS label, uniq(person_id) AS users
                  FROM events WHERE ${where} AND timestamp >= now() - INTERVAL 7 DAY
                  GROUP BY label ORDER BY users DESC LIMIT 6`,
                  values
              )
    return {
        daily: hogql(
            `SELECT toStartOfDay(timestamp) AS day, uniq(person_id) AS users, count() AS total
            FROM events WHERE ${where} AND timestamp >= toDateTime({from})
            GROUP BY day ORDER BY day`,
            values
        ),
        week: hogql(
            `SELECT uniq(person_id) AS users, count() AS total
            FROM events WHERE ${where} AND timestamp >= now() - INTERVAL 7 DAY`,
            values
        ),
        split,
    }
}

function splitLabel(kind: UsageKind, label: string): string {
    if (kind === 'early_access') {
        return label === 'true' ? 'Opted in' : label === 'false' ? 'Opted out' : label
    }
    if (kind === 'flag' || kind === 'experiment') {
        return label === 'true' ? 'Got the feature' : label === 'false' ? 'Did not get it' : label
    }
    return label
}

export function parseUsage(kind: UsageKind, daily: unknown[][], week: unknown[][], split: unknown[][]): LaneUsage {
    return {
        days: daily.map(([day, users, total]) => ({
            day: dayjs(String(day)).format('YYYY-MM-DD'),
            users: Number(users),
            total: Number(total),
        })),
        weekUsers: Number(week[0]?.[0] ?? 0),
        weekTotal: Number(week[0]?.[1] ?? 0),
        split:
            kind === 'survey'
                ? ['Shown', 'Answered', 'Dismissed'].map((label, index) => ({
                      label,
                      users: Number(split[0]?.[index] ?? 0),
                  }))
                : split
                      .map(([label, users]) => ({ label: splitLabel(kind, String(label)), users: Number(users) }))
                      .filter((item) => item.users > 0),
    }
}
