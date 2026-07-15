import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { ApiConfig } from 'lib/api'
import { dayjs } from 'lib/dayjs'

import {
    engineeringAnalyticsTeamCiActivity,
    engineeringAnalyticsTeamCiHealth,
    engineeringAnalyticsTeamMergeTrend,
} from '../generated/api'
import type { teamDetailLogicType } from './teamDetailLogicType'
import { TeamCIHealthRow, TeamsWindow, UNOWNED_TEAM } from './teamsLogic'

const projectId = (): string => String(ApiConfig.getCurrentProjectId())

export interface TeamDetailLogicProps {
    ownerTeam: string
}

export interface TeamDailyPoint {
    day: string
    failedCount: number
    rerunPassedCount: number
    xfailedCount: number
}

export interface TeamTestSignalRow {
    nodeid: string
    selector: string
    signalCount: number
    signalCountPrior: number
    lastSeenAt: string
}

export interface TeamActivityData {
    days: TeamDailyPoint[]
    tests: TeamTestSignalRow[]
    truncatedTests: boolean
}

export interface TeamMergePoint {
    day: string
    teamMedianSeconds: number | null
    teamMergedCount: number
    repoMedianSeconds: number | null
    repoMergedCount: number
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
                        days: data.days.map((d) => ({
                            day: d.day,
                            failedCount: d.failed_count,
                            rerunPassedCount: d.rerun_passed_count,
                            xfailedCount: d.xfailed_count,
                        })),
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
                            teamMedianSeconds: p.team_median_seconds ?? null,
                            teamMergedCount: p.team_merged_count,
                            repoMedianSeconds: p.repo_median_seconds ?? null,
                            repoMergedCount: p.repo_merged_count,
                        })),
                    }
                },
            },
        ],
        rosterRow: [
            null as TeamCIHealthRow | null,
            {
                // The roster carries this team's headline twins (current + prior counts); the
                // detail page reuses that shape rather than growing a second aggregate endpoint.
                loadRosterRow: async (): Promise<TeamCIHealthRow | null> => {
                    const data = await engineeringAnalyticsTeamCiHealth(projectId(), { date_from: values.window })
                    const item = data.items.find((it) => it.owner_team === props.ownerTeam)
                    return item
                        ? {
                              ownerTeam: item.owner_team,
                              flakyTestCount: item.flaky_test_count,
                              flakyTestCountPrior: item.flaky_test_count_prior,
                              failedCount: item.failed_count,
                              failedCountPrior: item.failed_count_prior,
                              rerunPassedCount: item.rerun_passed_count,
                              rerunPassedCountPrior: item.rerun_passed_count_prior,
                              xfailedCount: item.xfailed_count,
                              xfailedCountPrior: item.xfailed_count_prior,
                              lastSeenAt: item.last_seen_at,
                          }
                        : null
                },
            },
        ],
    })),
    selectors({
        ownerTeam: [(_, p) => [p.ownerTeam], (ownerTeam: string) => ownerTeam],
        /** Zero-filled daily series across the whole window, so quiet days render as gaps, not skips. */
        filledDays: [
            (s) => [s.activity, s.window],
            (activity: TeamActivityData | null, window: TeamsWindow): TeamDailyPoint[] => {
                if (!activity) {
                    return []
                }
                const byDay = new Map(activity.days.map((d) => [dayjs(d.day).format('YYYY-MM-DD'), d]))
                const days: TeamDailyPoint[] = []
                const start = dayjs().subtract(WINDOW_DAYS[window] - 1, 'day')
                for (let i = 0; i < WINDOW_DAYS[window]; i++) {
                    const day = start.add(i, 'day').format('YYYY-MM-DD')
                    days.push(byDay.get(day) ?? { day, failedCount: 0, rerunPassedCount: 0, xfailedCount: 0 })
                }
                return days
            },
        ],
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
                    points.push(
                        byDay.get(day) ?? {
                            day,
                            teamMedianSeconds: null,
                            teamMergedCount: 0,
                            repoMedianSeconds: null,
                            repoMergedCount: 0,
                        }
                    )
                }
                return points
            },
        ],
    }),
    listeners(({ actions }) => ({
        setWindow: () => {
            actions.loadActivity()
            actions.loadRosterRow()
            actions.loadMergeTrend()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadActivity()
        actions.loadRosterRow()
        actions.loadMergeTrend()
    }),
])
