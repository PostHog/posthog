import { ApiConfig, CountedPaginatedResponse } from 'lib/api'

import { LinkType } from '~/types'

import { linksCreate, linksDestroy, linksList, linksPartialUpdate, linksRetrieve } from './generated/api'

const projectId = (): string => String(ApiConfig.getCurrentProjectId())

export const generatedLinksApi = {
    async list(): Promise<CountedPaginatedResponse<LinkType>> {
        return (await linksList(projectId(), { limit: 100 })) as unknown as CountedPaginatedResponse<LinkType>
    },
    async get(id: string): Promise<LinkType> {
        return (await linksRetrieve(projectId(), id)) as unknown as LinkType
    },
    async create(data: Partial<LinkType>): Promise<LinkType> {
        return (await linksCreate(projectId(), data as Parameters<typeof linksCreate>[1])) as unknown as LinkType
    },
    async update(id: string, data: Partial<LinkType>): Promise<LinkType> {
        return (await linksPartialUpdate(
            projectId(),
            id,
            data as Parameters<typeof linksPartialUpdate>[2]
        )) as unknown as LinkType
    },
    async delete(id: string): Promise<void> {
        await linksDestroy(projectId(), id)
    },
}
