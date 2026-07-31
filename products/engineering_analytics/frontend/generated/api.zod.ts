/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { CISignalsConfigUpdateApi, QuarantineRequestApi } from './api.zod.schemas'

/**
 * Enable or disable all CI signal detectors in one transaction.
 */
export const EngineeringAnalyticsCiSignalsConfigUpdateBody = CISignalsConfigUpdateApi

/**
 * Opens a pull request that edits the repository's checked-in .test_quarantine.json — and, for a new quarantine, a tracking issue the PR links but does not close. The file stays the source of truth that CI enforces; this never bypasses it. A quarantine only affects CI runs that start after the PR merges.
 * @summary Quarantine, extend, or unquarantine a flaky test
 */
export const EngineeringAnalyticsQuarantineRequestBody = QuarantineRequestApi
