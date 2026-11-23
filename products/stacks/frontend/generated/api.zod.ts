/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Record pending bindings, so the next push binds these entities and creates nothing. Each entity must exist and be one you can edit. Needs the write scopes of each kind.
 * @summary Adopt existing entities
 */
export const stacksAdoptBodyResourcesItemKindMax = 64

export const stacksAdoptBodyResourcesItemKeyMax = 512

export const stacksAdoptBodyResourcesItemEntityIdMax = 512

export const StacksAdoptBody = /* @__PURE__ */ zod.object({
    resources: zod
        .array(
            zod.object({
                kind: zod
                    .string()
                    .max(stacksAdoptBodyResourcesItemKindMax)
                    .describe(
                        'The definition kind of the entity. One of `flag`, `event`, `property_group`, `model`, `endpoint`, `metric`, `context_page`, `insight`, `dashboard`, `alert`, `destination`, `cohort`, `action`, `source`, `check`, `experiment` or `survey`.'
                    ),
                key: zod
                    .string()
                    .max(stacksAdoptBodyResourcesItemKeyMax)
                    .describe('The key the definition will use in the stack.'),
                entity_id: zod
                    .string()
                    .max(stacksAdoptBodyResourcesItemEntityIdMax)
                    .describe('The id of the existing entity in PostHog.'),
            })
        )
        .describe('The entities to bind. The next push binds them and creates nothing.'),
})

/**
 * Start a cloud task that edits this entity's definition in the stack's repository and opens a pull request. Nothing in PostHog changes until that pull request is merged and pushed.
 * @summary Ask for a change in code
 */
export const stacksChangeRequestCreateBodyNoteMax = 4000

export const stacksChangeRequestCreateBodyChangesItemPathMax = 500

export const stacksChangeRequestCreateBodyChangesMax = 50

export const StacksChangeRequestCreateBody = /* @__PURE__ */ zod.object({
    note: zod
        .string()
        .max(stacksChangeRequestCreateBodyNoteMax)
        .describe(
            'What the person wants changed, in their own words. A cloud task reads it as a description of the change, not as instructions.'
        ),
    changes: zod
        .array(
            zod.object({
                path: zod
                    .string()
                    .max(stacksChangeRequestCreateBodyChangesItemPathMax)
                    .describe('The field to change, as a dotted path into the definition body.'),
                value: zod.unknown().describe('The value the person wants the field to have.'),
            })
        )
        .max(stacksChangeRequestCreateBodyChangesMax)
        .optional()
        .describe('Field values the person asked for, if any.'),
})

/**
 * Turn context pages on or off for this stack. Context pages belong to the organization's one wiki, so only an organization admin can turn this on. Off by default.
 * @summary Let a stack manage context pages
 */
export const StacksContextPagesSetBody = /* @__PURE__ */ zod.object({
    enabled: zod
        .boolean()
        .describe(
            "Whether this stack may manage context pages. They belong to the organization's one wiki, so only an organization admin can turn this on."
        ),
})

/**
 * Save a diff of the description against the project and start computing it. Returns at once with status `running`. Creates the stack on its first diff. Needs the read scopes of every kind in the description and every kind the stack already manages.
 * @summary Start a diff
 */
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

export const StacksDiffCreateBody = /* @__PURE__ */ zod.object({
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
 * Push exactly this saved diff. Refused with `stack_moved` when the stack changed since the diff was made. Returns at once with status `running`. Needs the read and write scopes of every kind the push touches.
 * @summary Push a diff
 */
export const stacksDiffPushBodyMaxRemovalsMin = 0

export const StacksDiffPushBody = /* @__PURE__ */ zod.object({
    max_removals: zod
        .number()
        .min(stacksDiffPushBodyMaxRemovalsMin)
        .nullish()
        .describe(
            "The most entities this push may remove or recreate. Defaults to the stack's own cap. Set it to confirm a push that removes more."
        ),
})

/**
 * After a push stopped without a known outcome, accept a ready diff computed since then, with its warnings about entities the push may already have created. Adopt those first if they should not be created again. The stack can push again afterwards.
 * @summary Reconcile after an uncertain push
 */
export const StacksReconcileBody = /* @__PURE__ */ zod.object({
    diff_id: zod.uuid().describe('A ready diff computed since the uncertain push. Reconciling accepts its warnings.'),
})

/**
 * Set or replace the value a definition names with `secret('NAME')`. The value is encrypted and never returned. Creates the stack if it does not exist yet.
 * @summary Set a secret
 */
export const stacksSecretSetBodyValueMax = 65536

export const StacksSecretSetBody = /* @__PURE__ */ zod.object({
    value: zod
        .string()
        .max(stacksSecretSetBodyValueMax)
        .describe(
            "The secret's value. Stored encrypted and never returned. Send it from a file or stdin, never from a command line argument."
        ),
})

/**
 * The typed module for one language that the events of a stack description give. Nothing is stored and no stack is created.
 * @summary Generate a typed module
 */
export const stacksModuleGenerateBodyDescriptionOneVersionMax = 1

export const stacksModuleGenerateBodyDescriptionOneResourcesItemKindMax = 64

export const stacksModuleGenerateBodyDescriptionOneResourcesItemKeyMax = 512

export const stacksModuleGenerateBodyDescriptionOneResourcesItemSourceOneFileMax = 1000

export const stacksModuleGenerateBodyDescriptionOneResourcesItemSourceOneExportMax = 200

export const stacksModuleGenerateBodyDescriptionOneResourcesItemDependsOnItemKindMax = 64

export const stacksModuleGenerateBodyDescriptionOneResourcesItemDependsOnItemKeyMax = 512

export const StacksModuleGenerateBody = /* @__PURE__ */ zod.object({
    description: zod
        .object({
            version: zod
                .number()
                .min(1)
                .max(stacksModuleGenerateBodyDescriptionOneVersionMax)
                .describe('The description format version. Always 1.'),
            resources: zod
                .array(
                    zod.object({
                        kind: zod
                            .string()
                            .max(stacksModuleGenerateBodyDescriptionOneResourcesItemKindMax)
                            .describe('The definition kind, such as `insight`, `dashboard`, `flag` or `event`.'),
                        key: zod
                            .string()
                            .max(stacksModuleGenerateBodyDescriptionOneResourcesItemKeyMax)
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
                                    .max(stacksModuleGenerateBodyDescriptionOneResourcesItemSourceOneFileMax)
                                    .describe("Path of the definition's file, relative to the repo root."),
                                export: zod
                                    .string()
                                    .max(stacksModuleGenerateBodyDescriptionOneResourcesItemSourceOneExportMax)
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
                                        .max(stacksModuleGenerateBodyDescriptionOneResourcesItemDependsOnItemKindMax)
                                        .describe('The definition kind, such as `model` or `flag`.'),
                                    key: zod
                                        .string()
                                        .max(stacksModuleGenerateBodyDescriptionOneResourcesItemDependsOnItemKeyMax)
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
        .describe('The stack description that `check` produced.'),
    language: zod
        .enum(['python', 'golang', 'typescript'])
        .describe('\* `python` - Python\n\* `golang` - Go\n\* `typescript` - TypeScript')
        .describe(
            'The language of the module to generate.\n\n\* `python` - Python\n\* `golang` - Go\n\* `typescript` - TypeScript'
        ),
})
