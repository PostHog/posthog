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
    EndpointLastExecutionTimesRequestApi,
    EndpointMaterializationSuggestionRequestApi,
    EndpointRequestApi,
    EndpointRunRequestApi,
    MaterializationPreviewRequestApi,
    PatchedEndpointRequestApi,
} from './api.zod.schemas'

/**
 * Create a new endpoint.
 */
export const EndpointsCreateBody = EndpointRequestApi

/**
 * Update an existing endpoint. Parameters are optional. Pass version in body or ?version=N query param to target a specific version.
 */
export const EndpointsUpdateBody = EndpointRequestApi

/**
 * Update an existing endpoint.
 */
export const EndpointsPartialUpdateBody = PatchedEndpointRequestApi

/**
 * Preview the materialization transform for an endpoint. Shows what the query will look like after materialization, including range pair detection and bucket functions.
 */
export const EndpointsMaterializationPreviewCreateBody = MaterializationPreviewRequestApi

/**
 * Ask AI to rewrite the endpoint's query into a semantically equivalent form that can be materialized. Only applicable to SQL (HogQL) endpoints that currently fail the materialization checks. The suggestion is validated against the live checks before being returned; nothing is saved. Requires the organization's AI data processing approval.
 */
export const EndpointsMaterializationSuggestionCreateBody = EndpointMaterializationSuggestionRequestApi

/**
 * Execute endpoint with optional materialization. Supports version parameter, runs latest version if not set.
 */
export const EndpointsRunCreateBody = EndpointRunRequestApi

/**
 * Get the most recent execution time per endpoint (endpoint-level). Timestamps are recorded by the run path for personal-API-key calls. For per-version usage, query the query_log table directly.
 */
export const EndpointsLastExecutionTimesCreateBody = EndpointLastExecutionTimesRequestApi
