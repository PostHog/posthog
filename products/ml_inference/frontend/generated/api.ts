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
import type {
    DecideRequestApi,
    DecideResponseApi,
    SearchIntentRequestApi,
    SearchIntentResponseApi,
} from './api.schemas'

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

export const getMlInferenceSearchIntentClassifyCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/ml_inference/search_intent/classify/`
}

/**
 * Guess which filter picker tab a search belongs to, so the picker can suggest or promote it.
 * @summary Classify a filter picker search
 */
export const mlInferenceSearchIntentClassifyCreate = async (
    projectId: string,
    searchIntentRequestApi: SearchIntentRequestApi,
    options?: RequestInit
): Promise<SearchIntentResponseApi> => {
    return apiMutator<SearchIntentResponseApi>(getMlInferenceSearchIntentClassifyCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(searchIntentRequestApi),
    })
}
