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
 * List managed migrations using the response serializer
 */
export const ManagedMigrationsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod
            .object({
                id: zod.uuid(),
                team_id: zod.number(),
                created_at: zod.iso.datetime({}),
                updated_at: zod.iso.datetime({}),
                state: zod.unknown().nullable(),
                created_by: zod.object({}).nullable(),
                status: zod
                    .enum(['completed', 'failed', 'paused', 'running'])
                    .optional()
                    .describe(
                        '* `completed` - Completed\n* `failed` - Failed\n* `paused` - Paused\n* `running` - Running'
                    ),
                display_status_message: zod.string().nullable(),
                import_config: zod.unknown(),
            })
            .describe('Serializer for BatchImport model')
    ),
})

/**
 * Viewset for BatchImport model
 */
export const ManagedMigrationsRetrieveResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        team_id: zod.number(),
        created_at: zod.iso.datetime({}),
        updated_at: zod.iso.datetime({}),
        state: zod.unknown().nullable(),
        created_by: zod.object({}).nullable(),
        status: zod
            .enum(['completed', 'failed', 'paused', 'running'])
            .optional()
            .describe('* `completed` - Completed\n* `failed` - Failed\n* `paused` - Paused\n* `running` - Running'),
        display_status_message: zod.string().nullable(),
        import_config: zod.unknown(),
    })
    .describe('Serializer for BatchImport model')

/**
 * Viewset for BatchImport model
 */
export const ManagedMigrationsUpdateBody = /* @__PURE__ */ zod
    .object({
        status: zod
            .enum(['completed', 'failed', 'paused', 'running'])
            .optional()
            .describe('* `completed` - Completed\n* `failed` - Failed\n* `paused` - Paused\n* `running` - Running'),
        import_config: zod.unknown(),
    })
    .describe('Serializer for BatchImport model')

export const ManagedMigrationsUpdateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        team_id: zod.number(),
        created_at: zod.iso.datetime({}),
        updated_at: zod.iso.datetime({}),
        state: zod.unknown().nullable(),
        created_by: zod.object({}).nullable(),
        status: zod
            .enum(['completed', 'failed', 'paused', 'running'])
            .optional()
            .describe('* `completed` - Completed\n* `failed` - Failed\n* `paused` - Paused\n* `running` - Running'),
        display_status_message: zod.string().nullable(),
        import_config: zod.unknown(),
    })
    .describe('Serializer for BatchImport model')

/**
 * Viewset for BatchImport model
 */
export const ManagedMigrationsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        status: zod
            .enum(['completed', 'failed', 'paused', 'running'])
            .optional()
            .describe('* `completed` - Completed\n* `failed` - Failed\n* `paused` - Paused\n* `running` - Running'),
        import_config: zod.unknown().optional(),
    })
    .describe('Serializer for BatchImport model')

export const ManagedMigrationsPartialUpdateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        team_id: zod.number(),
        created_at: zod.iso.datetime({}),
        updated_at: zod.iso.datetime({}),
        state: zod.unknown().nullable(),
        created_by: zod.object({}).nullable(),
        status: zod
            .enum(['completed', 'failed', 'paused', 'running'])
            .optional()
            .describe('* `completed` - Completed\n* `failed` - Failed\n* `paused` - Paused\n* `running` - Running'),
        display_status_message: zod.string().nullable(),
        import_config: zod.unknown(),
    })
    .describe('Serializer for BatchImport model')

/**
 * Pause a running batch import.
 */
export const ManagedMigrationsPauseCreateBody = /* @__PURE__ */ zod
    .object({
        status: zod
            .enum(['completed', 'failed', 'paused', 'running'])
            .optional()
            .describe('* `completed` - Completed\n* `failed` - Failed\n* `paused` - Paused\n* `running` - Running'),
        import_config: zod.unknown(),
    })
    .describe('Serializer for BatchImport model')

export const ManagedMigrationsPauseCreateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        team_id: zod.number(),
        created_at: zod.iso.datetime({}),
        updated_at: zod.iso.datetime({}),
        state: zod.unknown().nullable(),
        created_by: zod.object({}).nullable(),
        status: zod
            .enum(['completed', 'failed', 'paused', 'running'])
            .optional()
            .describe('* `completed` - Completed\n* `failed` - Failed\n* `paused` - Paused\n* `running` - Running'),
        display_status_message: zod.string().nullable(),
        import_config: zod.unknown(),
    })
    .describe('Serializer for BatchImport model')

/**
 * Resume a paused batch import.
 */
export const ManagedMigrationsResumeCreateBody = /* @__PURE__ */ zod
    .object({
        status: zod
            .enum(['completed', 'failed', 'paused', 'running'])
            .optional()
            .describe('* `completed` - Completed\n* `failed` - Failed\n* `paused` - Paused\n* `running` - Running'),
        import_config: zod.unknown(),
    })
    .describe('Serializer for BatchImport model')

export const ManagedMigrationsResumeCreateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        team_id: zod.number(),
        created_at: zod.iso.datetime({}),
        updated_at: zod.iso.datetime({}),
        state: zod.unknown().nullable(),
        created_by: zod.object({}).nullable(),
        status: zod
            .enum(['completed', 'failed', 'paused', 'running'])
            .optional()
            .describe('* `completed` - Completed\n* `failed` - Failed\n* `paused` - Paused\n* `running` - Running'),
        display_status_message: zod.string().nullable(),
        import_config: zod.unknown(),
    })
    .describe('Serializer for BatchImport model')
