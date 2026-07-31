/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import {
    BlastRadiusRequestApi,
    HogFlowApi,
    HogFlowBatchJobApi,
    HogFlowInvocationApi,
    HogFlowPublishRequestApi,
    HogFlowRevisionRestoreRequestApi,
    HogFlowScheduleApi,
    HogFlowTemplateApi,
    HogInvocationRerunRequestApi,
    PatchedHogFlowApi,
    PatchedHogFlowGraphUpdateApi,
    PatchedHogFlowScheduleApi,
    PatchedHogFlowTemplateApi,
} from './api.zod.schemas'

export const HogFlowTemplatesCreateBody = HogFlowTemplateApi

export const HogFlowTemplatesUpdateBody = HogFlowTemplateApi

export const HogFlowTemplatesPartialUpdateBody = PatchedHogFlowTemplateApi

export const HogFlowsCreateBody = HogFlowApi

export const HogFlowsUpdateBody = HogFlowApi

export const HogFlowsPartialUpdateBody = PatchedHogFlowApi

export const HogFlowsBatchJobsCreateBody = HogFlowBatchJobApi

export const HogFlowsGraphPartialUpdateBody = PatchedHogFlowGraphUpdateApi

export const HogFlowsInvocationsCreateBody = HogFlowInvocationApi

export const HogFlowsPublishCreateBody = HogFlowPublishRequestApi

/**
 * Rerun past invocations of this hog flow from their stored payloads.
 *
 * Same shape and semantics as the hog function rerun endpoint —
 * proxies through to the CDP worker, which reads matching rows from
 * ClickHouse, rehydrates from `invocation_globals`, and re-enqueues
 * onto cyclotron with `is_retry=1`.
 *
 * Because rerun replays historical event/person/group data, it requires
 * `person:read` and `group:read` on top of `hog_flow:write`.
 */
export const HogFlowsRerunCreateBody = HogInvocationRerunRequestApi

export const HogFlowsRevisionsRestoreCreateBody = HogFlowRevisionRestoreRequestApi

export const HogFlowsSchedulesCreateBody = HogFlowScheduleApi

export const HogFlowsSchedulesPartialUpdateBody = PatchedHogFlowScheduleApi

export const HogFlowsBulkDeleteCreateBody = HogFlowApi

export const HogFlowsUserBlastRadiusCreateBody = BlastRadiusRequestApi
