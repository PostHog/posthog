/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 6 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Each entity the stack manages or has adopted, one page per call.
 * @summary List a stack's bindings
 */
export const StacksBindingsListParams = () => zod.object({
    name: zod.string().describe('The stack name, as `posthog.json` sets it.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Save a diff of the description against the project and start computing it. Returns at once with status `running`. Creates the stack on its first diff. Needs the read scopes of every kind in the description and every kind the stack already manages.
 * @summary Start a diff
 */
export const StacksDiffCreateParams = () => zod.object({
    name: zod.string().describe('The stack name, as `posthog.json` sets it.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const stacksDiffCreateBodyDescriptionOneVersionMax = 1

export const stacksDiffCreateBodyDescriptionOneResourcesItemKindMax = 64

export const stacksDiffCreateBodyDescriptionOneResourcesItemKeyMax = 512

export const stacksDiffCreateBodyDescriptionOneResourcesItemSourceOneFileMax = 1000

export const stacksDiffCreateBodyDescriptionOneResourcesItemSourceOneExportMax = 200

export const stacksDiffCreateBodyDescriptionOneResourcesItemDependsOnItemKindMax = 64

export const stacksDiffCreateBodyDescriptionOneResourcesItemDependsOnItemKeyMax = 512

export const stacksDiffCreateBodySourceOneRepositoryMax = 500

export const stacksDiffCreateBodySourceOneBranchMax = 500

export const stacksDiffCreateBodySourceOneCommitMax = 100

export const StacksDiffCreateBody = () => zod.object({
    description: zod
        .object({
            version: zod
                .number()
                .min(1)
                .max(stacksDiffCreateBodyDescriptionOneVersionMax)
                .describe('The description format version. Always 1.'),
            resources: zod
                .array(
                    zod.object({
                        kind: zod
                            .string()
                            .max(stacksDiffCreateBodyDescriptionOneResourcesItemKindMax)
                            .describe('The definition kind, such as `insight`, `dashboard`, `flag` or `event`.'),
                        key: zod
                            .string()
                            .max(stacksDiffCreateBodyDescriptionOneResourcesItemKeyMax)
                            .describe(
                                'The identity the author chose, unique within the kind. For a kind with a natural key, such as a flag key or an event name, it is that natural key.'
                            ),
                        body: zod
                            .record(zod.string(), zod.unknown())
                            .describe(
                                'The definition, shaped like the API\'s create body for the kind. A reference to another definition in the stack is `{\"$ref\": {\"kind\", \"key\", \"attr\"}}`, and a secret is `{\"$secret\": \"NAME\"}`.'
                            ),
                        source: zod
                            .object({
                                file: zod
                                    .string()
                                    .max(stacksDiffCreateBodyDescriptionOneResourcesItemSourceOneFileMax)
                                    .describe("Path of the definition's file, relative to the repo root."),
                                export: zod
                                    .string()
                                    .max(stacksDiffCreateBodyDescriptionOneResourcesItemSourceOneExportMax)
                                    .optional()
                                    .describe('Name of the export in that file that holds the definition.'),
                            })
                            .optional()
                            .describe('Where the definition lives in the repository, for messages and provenance.'),
                        depends_on: zod
                            .array(
                                zod.object({
                                    kind: zod
                                        .string()
                                        .max(stacksDiffCreateBodyDescriptionOneResourcesItemDependsOnItemKindMax)
                                        .describe('The definition kind, such as `model` or `flag`.'),
                                    key: zod
                                        .string()
                                        .max(stacksDiffCreateBodyDescriptionOneResourcesItemDependsOnItemKeyMax)
                                        .describe("The definition's key in the same stack."),
                                })
                            )
                            .optional()
                            .describe(
                                "Definitions in the same stack that must exist before this one is created, because the body names them by a string rather than a reference, such as a model that another model's SQL reads."
                            ),
                    })
                )
                .describe('Every definition the stack manages, sorted by kind and then key.'),
        })
        .describe('The stack description that `hog check` writes.'),
    source: zod
        .object({
            repository: zod
                .string()
                .max(stacksDiffCreateBodySourceOneRepositoryMax)
                .describe('The repository the description was built from, such as `org\/repo`.'),
            branch: zod
                .string()
                .max(stacksDiffCreateBodySourceOneBranchMax)
                .describe('The branch the description was built from.'),
            commit: zod
                .string()
                .max(stacksDiffCreateBodySourceOneCommitMax)
                .describe('The commit the description was built from.'),
        })
        .describe('The repository, branch and commit the description came from.'),
})

/**
 * The diff and its status. A push's progress shows here too. Needs the read scopes the diff ran with. Field values are shown to the person who made the diff and to project admins.
 * @summary Read a diff
 */
export const StacksDiffRetrieveParams = () => zod.object({
    diff_id: zod.string().describe('The id of a saved diff of this stack.'),
    name: zod.string().describe('The stack name, as `posthog.json` sets it.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Push exactly this saved diff. Refused with `stack_moved` when the stack changed since the diff was made. Returns at once with status `running`. Needs the read and write scopes of every kind the push touches.
 * @summary Push a diff
 */
export const StacksDiffPushParams = () => zod.object({
    diff_id: zod.string().describe('The id of a saved diff of this stack.'),
    name: zod.string().describe('The stack name, as `posthog.json` sets it.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const stacksDiffPushBodyMaxRemovalsMin = 0

export const StacksDiffPushBody = () => zod.object({
    max_removals: zod
        .number()
        .min(stacksDiffPushBodyMaxRemovalsMin)
        .nullish()
        .describe(
            "The most entities this push may remove or recreate. Defaults to the stack's own cap. Set it to confirm a push that removes more."
        ),
})

/**
 * The binding that manages this entity, or null when no stack does.
 * @summary Find what manages an entity
 */
export const StacksBindingLookupParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const stacksBindingLookupQueryEntityIdMax = 512

export const stacksBindingLookupQueryKindMax = 64

export const StacksBindingLookupQueryParams = () => zod.object({
    entity_id: zod
        .string()
        .min(1)
        .max(stacksBindingLookupQueryEntityIdMax)
        .describe(
            'The id of the entity in PostHog. For a kind whose key is a name, such as an event name or a context page path, that name finds it too.'
        ),
    kind: zod
        .string()
        .min(1)
        .max(stacksBindingLookupQueryKindMax)
        .describe(
            'The definition kind of the entity. One of `flag`, `event`, `property_group`, `model`, `endpoint`, `metric`, `context_page`, `insight`, `dashboard`, `alert`, `destination`, `cohort`, `action`, `source`, `check`, `experiment` or `survey`.'
        ),
})

/**
 * Each kind of entity some stack in this project manages, with the stack and its repository. Before creating an entity of a listed kind, add its definition in that repository instead.
 * @summary List the kinds managed in code
 */
export const StacksManagedKindsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})
