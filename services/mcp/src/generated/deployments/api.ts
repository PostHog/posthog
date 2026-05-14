/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 5 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * CRUD for DeploymentProject (the connected-repo + hosting-target entity).

Create-time provisioning calls Cloudflare BEFORE writing the DB row
(see services/provision_project.py for the rationale). Delete is a
soft-delete; Cloudflare-side cleanup is deferred to a periodic Celery
task.
 */
export const DeploymentProjectsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DeploymentProjectsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    ordering: zod.string().optional().describe('Which field to use when ordering the results.'),
    search: zod.string().optional().describe('A search term.'),
})

/**
 * Full lifecycle viewset for Deployments.

All deployments are scoped to a parent DeploymentProject via the URL
parent lookup `deployment_project_id`. The viewset enforces that
scoping in `safely_get_queryset` so a user can never see / mutate a
deployment that doesn't belong to the project in the URL.
 */
export const DeploymentProjectsDeploymentsListParams = /* @__PURE__ */ zod.object({
    deployment_project_id: zod.string().describe('UUID of the parent DeploymentProject.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DeploymentProjectsDeploymentsListQueryParams = /* @__PURE__ */ zod.object({
    author: zod.string().optional().describe('Commit author email address to include.'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    ordering: zod.string().optional().describe('Which field to use when ordering the results.'),
    search: zod.string().optional().describe('A search term.'),
    status: zod.string().optional().describe('Comma-separated deployment statuses to include.'),
})

/**
 * Full lifecycle viewset for Deployments.

All deployments are scoped to a parent DeploymentProject via the URL
parent lookup `deployment_project_id`. The viewset enforces that
scoping in `safely_get_queryset` so a user can never see / mutate a
deployment that doesn't belong to the project in the URL.
 */
export const DeploymentProjectsDeploymentsRetrieveParams = /* @__PURE__ */ zod.object({
    deployment_project_id: zod.string().describe('UUID of the parent DeploymentProject.'),
    id: zod.string().describe('A UUID string identifying this deployment.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Full lifecycle viewset for Deployments.

All deployments are scoped to a parent DeploymentProject via the URL
parent lookup `deployment_project_id`. The viewset enforces that
scoping in `safely_get_queryset` so a user can never see / mutate a
deployment that doesn't belong to the project in the URL.
 */
export const DeploymentProjectsDeploymentsEventsListParams = /* @__PURE__ */ zod.object({
    deployment_project_id: zod.string().describe('UUID of the parent DeploymentProject.'),
    id: zod.string().describe('A UUID string identifying this deployment.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DeploymentProjectsDeploymentsEventsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * CRUD for DeploymentProject (the connected-repo + hosting-target entity).

Create-time provisioning calls Cloudflare BEFORE writing the DB row
(see services/provision_project.py for the rationale). Delete is a
soft-delete; Cloudflare-side cleanup is deferred to a periodic Celery
task.
 */
export const DeploymentProjectsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this deployment project.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})
