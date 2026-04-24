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

export const eventDefinitionsCreateBodyNameMax = 400

export const eventDefinitionsCreateBodyPostToSlackDefault = false

export const EventDefinitionsCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(eventDefinitionsCreateBodyNameMax),
        owner: zod.number().nullish(),
        description: zod.string().nullish(),
        tags: zod.array(zod.unknown()).optional(),
        verified: zod.boolean().optional(),
        hidden: zod.boolean().nullish(),
        enforcement_mode: zod.enum(['allow', 'reject']).optional().describe('* `allow` - Allow\n* `reject` - Reject'),
        post_to_slack: zod.boolean().default(eventDefinitionsCreateBodyPostToSlackDefault),
        default_columns: zod.array(zod.string()).optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const eventDefinitionsUpdateBodyNameMax = 400

export const eventDefinitionsUpdateBodyPostToSlackDefault = false

export const EventDefinitionsUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(eventDefinitionsUpdateBodyNameMax),
        owner: zod.number().nullish(),
        description: zod.string().nullish(),
        tags: zod.array(zod.unknown()).optional(),
        verified: zod.boolean().optional(),
        hidden: zod.boolean().nullish(),
        enforcement_mode: zod.enum(['allow', 'reject']).optional().describe('* `allow` - Allow\n* `reject` - Reject'),
        post_to_slack: zod.boolean().default(eventDefinitionsUpdateBodyPostToSlackDefault),
        default_columns: zod.array(zod.string()).optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const eventDefinitionsPartialUpdateBodyNameMax = 400

export const eventDefinitionsPartialUpdateBodyPostToSlackDefault = false

export const EventDefinitionsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(eventDefinitionsPartialUpdateBodyNameMax).optional(),
        owner: zod.number().nullish(),
        description: zod.string().nullish(),
        tags: zod.array(zod.unknown()).optional(),
        verified: zod.boolean().optional(),
        hidden: zod.boolean().nullish(),
        enforcement_mode: zod.enum(['allow', 'reject']).optional().describe('* `allow` - Allow\n* `reject` - Reject'),
        post_to_slack: zod.boolean().default(eventDefinitionsPartialUpdateBodyPostToSlackDefault),
        default_columns: zod.array(zod.string()).optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

/**
 * Bulk update tags on multiple objects.

Accepts:
- {"ids": [...], "action": "add"|"remove"|"set", "tags": ["tag1", "tag2"]}

Actions:
- "add": Add tags to existing tags on each object
- "remove": Remove specific tags from each object
- "set": Replace all tags on each object with the provided list
 */
export const eventDefinitionsBulkUpdateTagsCreateBodyIdsMax = 500

export const EventDefinitionsBulkUpdateTagsCreateBody = /* @__PURE__ */ zod.object({
    ids: zod
        .array(zod.number())
        .max(eventDefinitionsBulkUpdateTagsCreateBodyIdsMax)
        .describe('List of object IDs to update tags on.'),
    action: zod
        .enum(['add', 'remove', 'set'])
        .describe('* `add` - add\n* `remove` - remove\n* `set` - set')
        .describe(
            "'add' merges with existing tags, 'remove' deletes specific tags, 'set' replaces all tags.\n\n* `add` - add\n* `remove` - remove\n* `set` - set"
        ),
    tags: zod.array(zod.string()).describe('Tag names to add, remove, or set.'),
})
