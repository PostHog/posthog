import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { ApiConfig } from 'lib/api'

import { engineeringAnalyticsTeamCiHealth } from '../generated/api'
import { engineeringAnalyticsLogic } from './engineeringAnalyticsLogic'
import type { teamsLogicType } from './teamsLogicType'

const projectId = (): string => String(ApiConfig.getCurrentProjectId())

export type TeamsWindow = '-24h' | '-7d' | '-14d' | '-30d'

export const UNOWNED_TEAM = 'unowned'

export interface TeamCIHealthRow {
    ownerTeam: string
    flakyTestCount: number
    flakyTestCountPrior: number
    failedCount: number
    failedCountPrior: number
    rerunPassedCount: number
    rerunPassedCountPrior: number
    xfailedCount: number
    xfailedCountPrior: number
    lastSeenAt: string
}

export interface TeamsData {
    rows: TeamCIHealthRow[]
    truncated: boolean
    limit: number
}

export const teamsLogic = kea<teamsLogicType>([
    path(['products', 'engineering_analytics', 'frontend', 'scenes', 'teamsLogic']),
    connect(() => ({
        values: [engineeringAnalyticsLogic, ['sourceId']],
        actions: [engineeringAnalyticsLogic, ['setSourceId']],
    })),
    actions({
        setTeamsWindow: (window: TeamsWindow) => ({ window }),
    }),
    reducers({
        teamsWindow: ['-14d' as TeamsWindow, { setTeamsWindow: (_, { window }) => window }],
    }),
    loaders(({ values }) => ({
        teams: [
            null as TeamsData | null,
            {
                loadTeams: async (): Promise<TeamsData> => {
                    const data = await engineeringAnalyticsTeamCiHealth(projectId(), {
                        date_from: values.teamsWindow,
                        source_id: values.sourceId ?? undefined,
                    })
                    return {
                        rows: data.items.map(
                            (it): TeamCIHealthRow => ({
                                ownerTeam: it.owner_team,
                                flakyTestCount: it.flaky_test_count,
                                flakyTestCountPrior: it.flaky_test_count_prior,
                                failedCount: it.failed_count,
                                failedCountPrior: it.failed_count_prior,
                                rerunPassedCount: it.rerun_passed_count,
                                rerunPassedCountPrior: it.rerun_passed_count_prior,
                                xfailedCount: it.xfailed_count,
                                xfailedCountPrior: it.xfailed_count_prior,
                                lastSeenAt: it.last_seen_at,
                            })
                        ),
                        truncated: data.truncated,
                        limit: data.limit,
                    }
                },
            },
        ],
    })),
    listeners(({ actions }) => ({
        setTeamsWindow: () => actions.loadTeams(),
        setSourceId: () => actions.loadTeams(),
    })),
    afterMount(({ actions }) => {
        actions.loadTeams()
    }),
])
