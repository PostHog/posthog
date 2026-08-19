import { ApiConfig } from 'lib/api'

import { EndpointType, EndpointVersionType } from '~/types'

import {
    endpointsCreate,
    endpointsDestroy,
    endpointsList,
    endpointsMaterializationStatusRetrieve,
    endpointsPartialUpdate,
    endpointsRetrieve,
    endpointsRunCreate,
    endpointsVersionsList,
} from './generated/api'

// nosemgrep: prefer-codegen-api
const projectId = (): string => String(ApiConfig.getCurrentProjectId())

export const endpointsApi = {
    async list(): Promise<{ results: EndpointType[] }> {
        return (await endpointsList(projectId())) as unknown as { results: EndpointType[] }
    },
    async retrieve(name: string, params?: Parameters<typeof endpointsRetrieve>[2]): Promise<EndpointVersionType> {
        return (await endpointsRetrieve(projectId(), name, params)) as unknown as EndpointVersionType
    },
    async versions(name: string): Promise<{ results: EndpointVersionType[] }> {
        return (await endpointsVersionsList(projectId(), name)) as unknown as { results: EndpointVersionType[] }
    },
    async create(data: unknown): Promise<EndpointVersionType> {
        return (await endpointsCreate(
            projectId(),
            data as Parameters<typeof endpointsCreate>[1]
        )) as unknown as EndpointVersionType
    },
    async update(name: string, data: unknown): Promise<EndpointVersionType> {
        return (await endpointsPartialUpdate(
            projectId(),
            name,
            data as Parameters<typeof endpointsPartialUpdate>[2]
        )) as unknown as EndpointVersionType
    },
    async destroy(name: string): Promise<void> {
        await endpointsDestroy(projectId(), name)
    },
    async materializationStatus(
        name: string,
        params?: Parameters<typeof endpointsMaterializationStatusRetrieve>[2]
    ): Promise<EndpointType['materialization']> {
        return (await endpointsMaterializationStatusRetrieve(
            projectId(),
            name,
            params
        )) as unknown as EndpointType['materialization']
    },
    async run(name: string, data: unknown) {
        return await endpointsRunCreate(projectId(), name, data as Parameters<typeof endpointsRunCreate>[2])
    },
}
