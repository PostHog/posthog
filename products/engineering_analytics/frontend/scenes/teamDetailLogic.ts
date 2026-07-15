import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { ApiConfig } from 'lib/api'
import { dayjs } from 'lib/dayjs'

import { engineeringAnalyticsTeamCiActivity, engineeringAnalyticsTeamMergeTrend } from '../generated/api'
import type { teamDetailLogicType } from './teamDetailLogicType'
import { TeamsWindow, UNOWNED_TEAM } from './teamsLogic'

const projectId = (): string => String(ApiConfig.getCurrentProjectId())

export interface TeamDetailLogicProps {
    ownerTeam: string
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
    mergedCount: number
}

export interface TeamMergeTrendData {
    hasMembershipData: boolean
    points: TeamMergePoint[]
}

const WINDOW_DAYS: Record<TeamsWindow, number> = { '-24h': 1, '-7d': 7, '-14d': 14, '-30d': 30 }

export const teamDetailLogic = kea<teamDetailLogicType>([
    path(['products', 'engineering_analytics', 'frontend', 'scenes', 'teamDetailLogic']),
    props({} as TeamDetailLogicProps),
    key((props) => props.ownerTeam),
    actions({
        setWindow: (window: TeamsWindow) => ({ window }),
    }),
    reducers({
        window: ['-14d' as TeamsWindow, { setWindow: (_, { window }) => window }],
    }),
    loaders(({ props, values }) => ({
        activity: [
            null as TeamActivityData | null,
            {
                loadActivity: async (): Promise<TeamActivityData> => {
                    const data = await engineeringAnalyticsTeamCiActivity(projectId(), {
                        owner_team: props.ownerTeam,
                        date_from: values.window,
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
                    // 'unowned' is an ownership gap, not an org team — a membership join has no meaning there.
                    if (props.ownerTeam === UNOWNED_TEAM) {
                        return null
                    }
                    const data = await engineeringAnalyticsTeamMergeTrend(projectId(), {
                        owner_team: props.ownerTeam,
                        date_from: values.window,
                    })
                    return {
                        hasMembershipData: data.has_membership_data,
                        points: data.points.map((p) => ({
                            day: p.day,
                            medianSeconds: p.median_seconds ?? null,
                            averageSeconds: p.average_seconds ?? null,
                            mergedCount: p.merged_count,
                        })),
                    }
                },
            },
        ],
    })),
    selectors({
        ownerTeam: [(_, p) => [p.ownerTeam], (ownerTeam: string) => ownerTeam],
        /** Merge-trend points across every day in the window; a day without merges keeps null medians
         *  so the lines gap honestly instead of dropping to zero. */
        filledMergePoints: [
            (s) => [s.mergeTrend, s.window],
            (mergeTrend: TeamMergeTrendData | null, window: TeamsWindow): TeamMergePoint[] => {
                if (!mergeTrend?.hasMembershipData) {
                    return []
                }
                const byDay = new Map(mergeTrend.points.map((p) => [dayjs(p.day).format('YYYY-MM-DD'), p]))
                const points: TeamMergePoint[] = []
                const start = dayjs().subtract(WINDOW_DAYS[window] - 1, 'day')
                for (let i = 0; i < WINDOW_DAYS[window]; i++) {
                    const day = start.add(i, 'day').format('YYYY-MM-DD')
                    points.push(byDay.get(day) ?? { day, medianSeconds: null, averageSeconds: null, mergedCount: 0 })
                }
                return points
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
