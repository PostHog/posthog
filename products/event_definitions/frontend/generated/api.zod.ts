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
    BulkUpdateTagsUUIDRequestApi,
    EnterpriseEventDefinitionApi,
    PatchedEnterpriseEventDefinitionApi,
} from './api.zod.schemas'

export const EventDefinitionsCreateBody = EnterpriseEventDefinitionApi

export const EventDefinitionsUpdateBody = EnterpriseEventDefinitionApi

export const EventDefinitionsPartialUpdateBody = PatchedEnterpriseEventDefinitionApi

/**
 * Add, remove, or replace tags across multiple event definitions in one request.
 *
 * Overrides ``TaggedItemViewSetMixin.bulk_update_tags``, which assumes integer PKs and runs
 * object-level access-control filtering. Event definitions use UUID PKs and are not an
 * object-level access-controlled resource — project membership (enforced by the viewset) is
 * the only boundary, matching the single-object update path — so this scopes by project and
 * skips the per-object editor check. Tags live on the base ``EventDefinition`` row, so it
 * operates there regardless of the enterprise extension.
 */
export const EventDefinitionsBulkUpdateTagsCreateBody = BulkUpdateTagsUUIDRequestApi
