/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 2 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Start the setup agent in the cloud on a GitHub repository of this project. It adds PostHog to the code and opens a pull request. Each user can have one setup run active per project at a time.
 * @summary Start a setup run
 */
export const WizardInstallsCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const wizardInstallsCreateBodyRepositoryMax = 255

export const wizardInstallsCreateBodyBranchMax = 255

export const wizardInstallsCreateBodyIdempotencyKeyMax = 255

export const WizardInstallsCreateBody = () => zod.object({
    repository: zod
        .string()
        .max(wizardInstallsCreateBodyRepositoryMax)
        .describe(
            "GitHub repository to set up, in owner\/name format. The project's GitHub connection must have access to it."
        ),
    branch: zod
        .string()
        .max(wizardInstallsCreateBodyBranchMax)
        .optional()
        .describe(
            "Branch to start from and to open the pull request against. Defaults to the repository's default branch."
        ),
    idempotency_key: zod
        .string()
        .max(wizardInstallsCreateBodyIdempotencyKeyMax)
        .optional()
        .describe(
            'Unique key for this request. A retry with the same key returns the same run instead of starting another.'
        ),
})

/**
 * Get the status of a cloud setup run, its task list, the pull request link once it exists, and a next step to relay to the user.
 * @summary Get a setup run's status
 */
export const wizardInstallsRetrievePathRunIdRegExp = new RegExp('^[0-9a-fA-F-]{36}$')

export const WizardInstallsRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    run_id: zod.string().regex(wizardInstallsRetrievePathRunIdRegExp),
})
