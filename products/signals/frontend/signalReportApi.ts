import { ApiConfig, CountedPaginatedResponse } from 'lib/api'

import {
    signalsReportArtefactsList,
    signalsReportsAvailableReviewersRetrieve,
    signalsReportsList,
    signalsReportsRetrieve,
    signalsReportsReviewersUpdate,
    signalsReportsStateCreate,
} from './generated/api'
import type { SignalsReportsListParams } from './generated/api.schemas'
import {
    SignalReport,
    SignalReportArtefact,
    SignalReportArtefactResponse,
    SignalReportStateRequest,
} from './inbox/types'

const projectId = (): string => String(ApiConfig.getCurrentProjectId())

type ReportListParams = SignalsReportsListParams & {
    actionability?: string
}

export const signalReportsApi = {
    async list(params?: ReportListParams): Promise<CountedPaginatedResponse<SignalReport>> {
        return (await signalsReportsList(
            projectId(),
            params as SignalsReportsListParams
        )) as unknown as CountedPaginatedResponse<SignalReport>
    },
    async get(id: string): Promise<SignalReport> {
        return (await signalsReportsRetrieve(projectId(), id)) as unknown as SignalReport
    },
    async artefacts(id: string, params: { limit?: number } = {}): Promise<SignalReportArtefactResponse> {
        return (await signalsReportArtefactsList(projectId(), id, params)) as SignalReportArtefactResponse
    },
    async setState(id: string, data: SignalReportStateRequest): Promise<SignalReport> {
        return (await signalsReportsStateCreate(
            projectId(),
            id,
            data as Parameters<typeof signalsReportsStateCreate>[2]
        )) as unknown as SignalReport
    },
    async availableReviewers(query?: string): Promise<{ user_uuid: string; name: string; email: string }[]> {
        const response = await signalsReportsAvailableReviewersRetrieve(projectId(), query ? { query } : undefined)
        return Object.entries(response).map(([user_uuid, { name, email }]) => ({ user_uuid, name, email }))
    },
    async setReviewers(reportId: string, content: Record<string, any>[]): Promise<SignalReportArtefact> {
        return (await signalsReportsReviewersUpdate(projectId(), reportId, { content })) as SignalReportArtefact
    },
}
