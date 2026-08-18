import api, { ApiConfig, ApiMethodOptions, PaginatedResponse } from 'lib/api'

import { CoreMemory } from '~/types'

import {
    coreMemoryCreate,
    coreMemoryList,
    coreMemoryPartialUpdate,
    getMaxHandsFreeSynthesizeCreateUrl,
    maxHandsFreeTokenCreate,
} from './generated/api'

const projectId = (): string => String(ApiConfig.getCurrentProjectId())

export const generatedCoreMemoryApi = {
    async list(): Promise<PaginatedResponse<CoreMemory>> {
        return (await coreMemoryList(projectId())) as unknown as PaginatedResponse<CoreMemory>
    },
    async create(data: Pick<CoreMemory, 'text'>): Promise<CoreMemory> {
        return (await coreMemoryCreate(projectId(), data)) as unknown as CoreMemory
    },
    async update(id: string, data: Pick<CoreMemory, 'text'>): Promise<CoreMemory> {
        return (await coreMemoryPartialUpdate(projectId(), id, data)) as unknown as CoreMemory
    },
}

export const generatedMaxHandsFreeApi = {
    async token(options?: RequestInit): Promise<{ token: string }> {
        return await maxHandsFreeTokenCreate(projectId(), options)
    },
    async synthesize(text: string, options?: ApiMethodOptions): Promise<Response> {
        return api.createResponse(getMaxHandsFreeSynthesizeCreateUrl(projectId()), { text }, options)
    },
}
