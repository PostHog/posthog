import { ApiConfig, PaginatedResponse } from 'lib/api'

import {
    signalsConfigCreate,
    signalsConfigList,
    signalsScoutRunsEmissionReports,
    signalsScoutRunsEmissionReportsBatch,
    signalsScoutRunsEmissions,
    signalsScoutRunsEmissionsBatch,
    signalsScoutRunsList,
    signalsSourceConfigsCreate,
    signalsSourceConfigsList,
    signalsSourceConfigsPartialUpdate,
    usersSignalAutonomyCreate,
    usersSignalAutonomyRetrieve,
} from './generated/api'
import {
    SignalScoutEmission,
    SignalScoutEmissionReportLink,
    SignalScoutRunSummary,
    SignalSourceConfig,
    SignalTeamConfig,
    SignalUserAutonomyConfig,
} from './inbox/types'

const projectId = (): string => String(ApiConfig.getCurrentProjectId())

export const signalSourceConfigsApi = {
    async list(): Promise<PaginatedResponse<SignalSourceConfig>> {
        return (await signalsSourceConfigsList(projectId())) as unknown as PaginatedResponse<SignalSourceConfig>
    },
    async create(data: Partial<SignalSourceConfig>): Promise<SignalSourceConfig> {
        return (await signalsSourceConfigsCreate(
            projectId(),
            data as Parameters<typeof signalsSourceConfigsCreate>[1]
        )) as SignalSourceConfig
    },
    async update(id: string, data: Partial<SignalSourceConfig>): Promise<SignalSourceConfig> {
        return (await signalsSourceConfigsPartialUpdate(
            projectId(),
            id,
            data as Parameters<typeof signalsSourceConfigsPartialUpdate>[2]
        )) as SignalSourceConfig
    },
}

export const signalTeamConfigApi = {
    async get(): Promise<SignalTeamConfig> {
        return (await signalsConfigList(projectId())) as unknown as SignalTeamConfig
    },
    async update(data: Partial<SignalTeamConfig>): Promise<SignalTeamConfig> {
        return (await signalsConfigCreate(
            projectId(),
            data as Parameters<typeof signalsConfigCreate>[1]
        )) as SignalTeamConfig
    },
}

export const signalScoutRunsApi = {
    async list(params?: Parameters<typeof signalsScoutRunsList>[1]): Promise<SignalScoutRunSummary[]> {
        return (await signalsScoutRunsList(projectId(), params)) as SignalScoutRunSummary[]
    },
    async emissions(runId: string): Promise<SignalScoutEmission[]> {
        return (await signalsScoutRunsEmissions(projectId(), runId)) as SignalScoutEmission[]
    },
    async emissionReports(runId: string): Promise<SignalScoutEmissionReportLink[]> {
        return (await signalsScoutRunsEmissionReports(projectId(), runId)) as SignalScoutEmissionReportLink[]
    },
    async emissionsBatch(runIds: string[]): Promise<SignalScoutEmission[]> {
        return (await signalsScoutRunsEmissionsBatch(projectId(), { run_ids: runIds })) as SignalScoutEmission[]
    },
    async emissionReportsBatch(runIds: string[]): Promise<SignalScoutEmissionReportLink[]> {
        return (await signalsScoutRunsEmissionReportsBatch(projectId(), {
            run_ids: runIds,
        })) as SignalScoutEmissionReportLink[]
    },
}

export const signalUserAutonomyApi = {
    async get(): Promise<SignalUserAutonomyConfig | null> {
        try {
            return (await usersSignalAutonomyRetrieve('@me')) as SignalUserAutonomyConfig
        } catch (error: any) {
            if (error?.status === 404) {
                return null
            }
            throw error
        }
    },
    async update(data: Partial<SignalUserAutonomyConfig>): Promise<SignalUserAutonomyConfig> {
        return (await usersSignalAutonomyCreate('@me', data)) as SignalUserAutonomyConfig
    },
}
