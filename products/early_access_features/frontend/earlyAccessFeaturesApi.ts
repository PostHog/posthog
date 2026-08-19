import { PaginatedResponse } from 'lib/api'
import { getCurrentTeamId } from 'lib/utils/getAppContext'

import { EarlyAccessFeatureType, NewEarlyAccessFeatureType } from '~/types'

import {
    earlyAccessFeatureCreate,
    earlyAccessFeatureDestroy,
    earlyAccessFeatureList,
    earlyAccessFeaturePartialUpdate,
    earlyAccessFeatureRetrieve,
} from './generated/api'

const projectId = (): string => String(getCurrentTeamId())

export const earlyAccessFeaturesApi = {
    async get(featureId: string): Promise<EarlyAccessFeatureType> {
        return (await earlyAccessFeatureRetrieve(projectId(), featureId)) as unknown as EarlyAccessFeatureType
    },
    async create(data: NewEarlyAccessFeatureType): Promise<EarlyAccessFeatureType> {
        return (await earlyAccessFeatureCreate(
            projectId(),
            data as Parameters<typeof earlyAccessFeatureCreate>[1]
        )) as unknown as EarlyAccessFeatureType
    },
    async delete(featureId: string): Promise<void> {
        await earlyAccessFeatureDestroy(projectId(), featureId)
    },
    async update(
        featureId: string,
        data: Partial<
            Pick<EarlyAccessFeatureType, 'name' | 'description' | 'stage' | 'documentation_url' | 'assignee'>
        > & { rollout_to_all?: boolean }
    ): Promise<EarlyAccessFeatureType> {
        return (await earlyAccessFeaturePartialUpdate(
            projectId(),
            featureId,
            data as Parameters<typeof earlyAccessFeaturePartialUpdate>[2]
        )) as unknown as EarlyAccessFeatureType
    },
    async list(): Promise<PaginatedResponse<EarlyAccessFeatureType>> {
        return (await earlyAccessFeatureList(projectId())) as unknown as PaginatedResponse<EarlyAccessFeatureType>
    },
}
