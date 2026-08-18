import { ApiConfig } from 'lib/api'

import {
    columnConfigurationsCreate,
    columnConfigurationsDestroy,
    columnConfigurationsList,
    columnConfigurationsPartialUpdate,
} from './generated/api'
import type { ColumnConfigurationApi, PaginatedColumnConfigurationListApi } from './generated/api.schemas'

const currentProjectId = (): string => String(ApiConfig.getCurrentProjectId())

export const generatedColumnConfigurations = {
    async list({
        teamId = ApiConfig.getCurrentTeamId(),
        context_key,
    }: { teamId?: number; context_key?: string } = {}): Promise<PaginatedColumnConfigurationListApi> {
        return await columnConfigurationsList(String(teamId), { context_key })
    },

    async create({
        teamId = ApiConfig.getCurrentTeamId(),
        data,
    }: {
        teamId?: number
        data: Partial<ColumnConfigurationApi>
    }): Promise<ColumnConfigurationApi> {
        return await columnConfigurationsCreate(
            String(teamId),
            data as Parameters<typeof columnConfigurationsCreate>[1]
        )
    },

    async update({
        teamId,
        id,
        data,
    }: {
        teamId?: number
        id: string
        data: Partial<ColumnConfigurationApi>
    }): Promise<ColumnConfigurationApi> {
        return await columnConfigurationsPartialUpdate(
            String(teamId ?? currentProjectId()),
            id,
            data as Parameters<typeof columnConfigurationsPartialUpdate>[2]
        )
    },

    async delete({ teamId, id }: { teamId?: number; id: string }): Promise<void> {
        await columnConfigurationsDestroy(String(teamId ?? currentProjectId()), id)
    },
}
