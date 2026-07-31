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
    ActivateVersionRequestApi,
    CreateAppInputApi,
    CreateVersionFromSourceInputApi,
    PatchedUpdateAppInputApi,
    UpdateAppInputApi,
    UploadVersionRequestApi,
} from './api.zod.schemas'

/**
 * @summary Create a streamlit app
 */
export const StreamlitAppsCreateBody = CreateAppInputApi

/**
 * @summary Update a streamlit app
 */
export const StreamlitAppsUpdateBody = UpdateAppInputApi

/**
 * @summary Partially update a streamlit app
 */
export const StreamlitAppsPartialUpdateBody = PatchedUpdateAppInputApi

/**
 * @summary Activate an existing app version
 */
export const StreamlitAppsActivateVersionCreateBody = ActivateVersionRequestApi

/**
 * @summary Create an app version from source code
 */
export const StreamlitAppsCreateVersionFromSourceCreateBody = CreateVersionFromSourceInputApi

/**
 * @summary Upload a new app version
 */
export const StreamlitAppsUploadVersionCreateBody = UploadVersionRequestApi
