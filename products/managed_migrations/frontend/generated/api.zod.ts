/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { BatchImportApi, PatchedBatchImportApi } from './api.zod.schemas'

/**
 * Create a new managed migration/batch import.
 */
export const ManagedMigrationsCreateBody = BatchImportApi

/**
 * Viewset for BatchImport model
 */
export const ManagedMigrationsUpdateBody = BatchImportApi

/**
 * Viewset for BatchImport model
 */
export const ManagedMigrationsPartialUpdateBody = PatchedBatchImportApi

/**
 * Pause a running batch import.
 */
export const ManagedMigrationsPauseCreateBody = BatchImportApi

/**
 * Resume a paused batch import.
 */
export const ManagedMigrationsResumeCreateBody = BatchImportApi
