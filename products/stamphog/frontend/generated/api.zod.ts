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
    DigestChannelApi,
    PatchedDigestChannelApi,
    PatchedStamphogRepoConfigApi,
    StamphogRepoConfigApi,
    StamphogSyncInstallationRequestApi,
} from './api.zod.schemas'

/**
 * Per-audience Slack destinations for the daily merged-PR digest.
 */
export const StamphogDigestChannelsCreateBody = DigestChannelApi

/**
 * Per-audience Slack destinations for the daily merged-PR digest.
 */
export const StamphogDigestChannelsUpdateBody = DigestChannelApi

/**
 * Per-audience Slack destinations for the daily merged-PR digest.
 */
export const StamphogDigestChannelsPartialUpdateBody = PatchedDigestChannelApi

/**
 * Per-repo stamphog settings — enable/disable review, GitHub App installation, policy overrides.
 */
export const StamphogRepoConfigsCreateBody = StamphogRepoConfigApi

/**
 * Per-repo stamphog settings — enable/disable review, GitHub App installation, policy overrides.
 */
export const StamphogRepoConfigsUpdateBody = StamphogRepoConfigApi

/**
 * Per-repo stamphog settings — enable/disable review, GitHub App installation, policy overrides.
 */
export const StamphogRepoConfigsPartialUpdateBody = PatchedStamphogRepoConfigApi

/**
 * Per-repo stamphog settings — enable/disable review, GitHub App installation, policy overrides.
 */
export const StamphogRepoConfigsSyncInstallationCreateBody = StamphogSyncInstallationRequestApi
