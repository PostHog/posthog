import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { ApiConfig } from 'lib/api'
import { Dayjs, dayjs } from 'lib/dayjs'

import { engineeringAnalyticsTeamCiActivity, engineeringAnalyticsTeamMergeTrend } from '../generated/api'
import type { teamDetailLogicType } from './teamDetailLogicType'
import { DEFAULT_TEAMS_WINDOW, TeamsWindow, UNOWNED_TEAM } from './teamsLogic'

const projectId = (): string => String(ApiConfig.getCurrentProjectId())

export interface TeamDetailLogicProps {
    ownerTeam: string
    sourceId: string | null
    window: TeamsWindow | null
}

export interface TeamTestSignalRow {
    nodeid: string
    selector: string
    signalCount: number
    signalCountPrior: number
    lastSeenAt: string
}

export interface TeamActivityData {
    tests: TeamTestSignalRow[]
    truncatedTests: boolean
}

export interface TeamMergePoint {
    day: string
    medianSeconds: number | null
    averageSeconds: number | null
}

export interface TeamMergeTrendData {
    hasMembershipData: boolean
    points: TeamMergePoint[]
}

export const teamDetailLogic = kea<teamDetailLogicType>([
    path(['products', 'engineering_analytics', 'frontend', 'scenes', 'teamDetailLogic']),
    props({} as TeamDetailLogicProps),
    key((props) => `${props.ownerTeam}@${props.sourceId ?? ''}`),
    actions({
        setWindow: (window: TeamsWindow) => ({ window }),
    }),
    reducers(({ props }) => ({
        window: [(props.window ?? DEFAULT_TEAMS_WINDOW) as TeamsWindow, { setWindow: (_, { window }) => window }],
    })),
    loaders(({ props, values }) => ({
        activity: [
            null as TeamActivityData | null,
            {
                loadActivity: async (): Promise<TeamActivityData> => {
                    const data = await engineeringAnalyticsTeamCiActivity(projectId(), {
                        owner_team: props.ownerTeam,
                        date_from: values.window,
                        source_id: props.sourceId ?? undefined,
                    })
                    return {
                        tests: data.tests.map((t) => ({
                            nodeid: t.nodeid,
                            selector: t.selector,
                            signalCount: t.signal_count,
                            signalCountPrior: t.signal_count_prior,
                            lastSeenAt: t.last_seen_at,
                        })),
                        truncatedTests: data.truncated_tests,
                    }
                },
            },
        ],
        mergeTrend: [
            null as TeamMergeTrendData | null,
            {
                loadMergeTrend: async (): Promise<TeamMergeTrendData | null> => {
                    // 'unowned' is an ownership gap, not an org team; a membership join has no meaning there.
                    if (props.ownerTeam === UNOWNED_TEAM) {
                        return null
                    }
                    const data = await engineeringAnalyticsTeamMergeTrend(projectId(), {
                        owner_team: props.ownerTeam,
                        date_from: values.window,
                        source_id: props.sourceId ?? undefined,
                    })
                    return {
                        hasMembershipData: data.has_membership_data,
                        points: data.points.map((p) => ({
                            day: p.day,
                            medianSeconds: p.median_seconds ?? null,
                            averageSeconds: p.average_seconds ?? null,
                        })),
                    }
                },
            },
        ],
    })),
    selectors({
        ownerTeam: [(_, p) => [p.ownerTeam], (ownerTeam: string) => ownerTeam],
        /** Quill-ready daily series on the backend's own day buckets. Gaps carry the last values
         *  forward: a day without merges means "nothing merged", not instant merges, so
         *  zero-filling would draw a false dip. Null when nothing merged in the window. */
        mergeTrendSeries: [
            (s) => [s.mergeTrend],
            (
                mergeTrend: TeamMergeTrendData | null
            ): { labels: string[]; median: number[]; average: number[] } | null => {
                if (!mergeTrend?.hasMembershipData) {
                    return null
                }
                const labels: string[] = []
                const median: number[] = []
                const average: number[] = []
                let lastDay: Dayjs | null = null
                let lastMedian = 0
                let lastAverage = 0
                for (const point of mergeTrend.points) {
                    const day = dayjs(point.day)
                    if (lastDay) {
                        for (let gap: Dayjs = lastDay.add(1, 'day'); gap.isBefore(day); gap = gap.add(1, 'day')) {
                            labels.push(gap.toISOString())
                            median.push(lastMedian)
                            average.push(lastAverage)
                        }
                    }
                    const medianValue: number | null = point.medianSeconds ?? (lastDay ? lastMedian : null)
                    const averageValue: number | null = point.averageSeconds ?? (lastDay ? lastAverage : null)
                    if (medianValue === null || averageValue === null) {
                        continue // Leading trim: no data yet to carry forward.
                    }
                    labels.push(day.toISOString())
                    median.push(medianValue)
                    average.push(averageValue)
                    lastDay = day
                    lastMedian = medianValue
                    lastAverage = averageValue
                }
                return labels.length ? { labels, median, average } : null
            },
        ],
    }),
    listeners(({ actions }) => ({
        setWindow: () => {
            actions.loadActivity()
            actions.loadMergeTrend()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadActivity()
        actions.loadMergeTrend()
    }),
])
