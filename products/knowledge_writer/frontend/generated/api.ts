import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator'
/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import type { MergePushApi, MergePushResponseApi } from './api.schemas'

export const getKnowledgeWriterMergePushesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/knowledge_writer/merge_pushes/`
}

export const knowledgeWriterMergePushesCreate = async (
    projectId: string,
    mergePushApi: MergePushApi,
    options?: RequestInit
): Promise<MergePushResponseApi> => {
    return apiMutator<MergePushResponseApi>(getKnowledgeWriterMergePushesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(mergePushApi),
    })
}
