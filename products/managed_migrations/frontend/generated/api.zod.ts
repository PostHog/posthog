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
 * Create a new managed migration/batch import.
 */
export const ManagedMigrationsCreateBody = /* @__PURE__ */ zod
    .object({
        status: zod
            .enum(['completed', 'failed', 'paused', 'running'])
            .optional()
            .describe('* `completed` - Completed\n* `failed` - Failed\n* `paused` - Paused\n* `running` - Running'),
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
