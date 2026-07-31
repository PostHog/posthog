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
    GitHubLinkExistingRequestApi,
    GitHubOAuthAuthorizeRequestApi,
    GitHubPrepareCallbackRequestApi,
    IntegrationAccessRequestApi,
    IntegrationConfigApi,
    PatchedIntegrationConfigApi,
    PatchedOrganizationIntegrationApi,
    RoleExternalReferenceApi,
} from './api.zod.schemas'

/**
 * ViewSet for organization-level integrations.
 *
 * Provides access to integrations that are scoped to the entire organization
 * (vs. project-level integrations). Examples include Vercel, AWS Marketplace, etc.
 *
 * Creation is handled by the integration installation flows
 * (e.g., Vercel marketplace installation). Users can disconnect integrations
 * via the DELETE endpoint.
 */
export const IntegrationsEnvironmentMappingPartialUpdateBody = PatchedOrganizationIntegrationApi

export const RoleExternalReferencesCreateBody = RoleExternalReferenceApi

export const IntegrationsCreateBody = IntegrationConfigApi

export const IntegrationsEmailPartialUpdateBody = PatchedIntegrationConfigApi

export const IntegrationsEmailVerifyCreateBody = IntegrationConfigApi

/**
 * Unified endpoint for generating Domain Connect apply URLs.
 *
 * Accepts a context ("email" or "proxy") and the relevant resource ID.
 * The backend resolves the domain, template variables, and service ID
 * based on context, then builds the signed apply URL.
 */
export const IntegrationsDomainConnectApplyUrlCreateBody = IntegrationConfigApi

/**
 * Reuse a GitHub installation already linked to a sibling team in the same organization.
 */
export const IntegrationsGithubLinkExistingCreateBody = GitHubLinkExistingRequestApi

/**
 * Mint a User OAuth URL to bootstrap a fresh `code` when the install flow returns without one.
 */
export const IntegrationsGithubOauthAuthorizeCreateBody = GitHubOAuthAuthorizeRequestApi

/**
 * Seed GitHub setup callback state without redirecting to GitHub.
 *
 * Used when the user opens an existing installation's settings on github.com (e.g. PostHog
 * Code "Update in GitHub") so the subsequent Setup URL redirect can be validated.
 */
export const IntegrationsGithubPrepareCallbackCreateBody = GitHubPrepareCallbackRequestApi

/**
 * Notify project admins that a member is requesting an integration be connected.
 */
export const IntegrationsRequestAccessCreateBody = IntegrationAccessRequestApi
