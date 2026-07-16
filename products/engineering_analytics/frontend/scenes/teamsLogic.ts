import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { ApiConfig } from 'lib/api'
import { dateMapping } from 'lib/utils/dateFilters'

import { engineeringAnalyticsTeamCiHealth } from '../generated/api'
import { engineeringAnalyticsLogic } from './engineeringAnalyticsLogic'
import type { teamsLogicType } from './teamsLogicType'

const projectId = (): string => String(ApiConfig.getCurrentProjectId())

export type TeamsWindow = '-24h' | '-7d' | '-14d' | '-30d'

export const DEFAULT_TEAMS_WINDOW: TeamsWindow = '-14d'

export const TEAMS_WINDOW_LABELS: Record<TeamsWindow, { prior: string; current: string }> = {
    '-24h': { prior: 'Previous 24 hours', current: 'Last 24 hours' },
    '-7d': { prior: 'Previous 7 days', current: 'Last 7 days' },
    '-14d': { prior: 'Previous 14 days', current: 'Last 14 days' },
    '-30d': { prior: 'Previous 30 days', current: 'Last 30 days' },
}

export function isTeamsWindow(value: unknown): value is TeamsWindow {
    return typeof value === 'string' && value in TEAMS_WINDOW_LABELS
}

// date_from presets the team endpoints accept (max 30d; an equal-length prior twin is scanned).
export const TEAMS_WINDOW_DATE_OPTIONS = dateMapping.filter(({ values }) => isTeamsWindow(values[0]))

export const UNOWNED_TEAM = 'unowned'

export interface TeamCIHealthRow {
    ownerTeam: string
    flakyTestCount: number
    flakyTestCountPrior: number
    failedCount: number
    failedCountPrior: number
    rerunPassedCount: number
    rerunPassedCountPrior: number
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
        teamsWindow: [DEFAULT_TEAMS_WINDOW as TeamsWindow, { setTeamsWindow: (_, { window }) => window }],
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
