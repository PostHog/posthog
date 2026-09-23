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
import type { DecideRequestApi, DecideResponseApi } from './api.schemas'

export const getMlInferenceDecisionsDecideCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/ml_inference/decisions/decide/`
}

/**
 * Ask the decision model typed questions about one piece of text and get a calibrated probability per question.
 * @summary Ask the decision model
 */
export const mlInferenceDecisionsDecideCreate = async (
    projectId: string,
    decideRequestApi: DecideRequestApi,
    options?: RequestInit
): Promise<DecideResponseApi> => {
    return apiMutator<DecideResponseApi>(getMlInferenceDecisionsDecideCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(decideRequestApi),
    })
}
