/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const BatchImportStatusEnumApi = zod
    .enum(['completed', 'failed', 'paused', 'running'])
    .describe('\* `completed` - Completed\n\* `failed` - Failed\n\* `paused` - Paused\n\* `running` - Running')

export type BatchImportStatusEnumApi = zod.input<typeof BatchImportStatusEnumApi>
export type BatchImportStatusEnumApiOutput = zod.output<typeof BatchImportStatusEnumApi>

export const DisplayStatusEnumApi = zod.enum(['waiting_to_start', 'running', 'paused', 'failed', 'completed'])

export type DisplayStatusEnumApi = zod.input<typeof DisplayStatusEnumApi>
export type DisplayStatusEnumApiOutput = zod.output<typeof DisplayStatusEnumApi>

export const BatchImportPartsProgressApi = zod.object({
    done: zod
        .number()
        .describe(
            'Number of finished parts (a part is done when its committed byte offset has reached its known total size).'
        ),
    total: zod.number().describe('Total number of parts the worker has planned for this import.'),
    inflight_key: zod
        .string()
        .nullable()
        .describe(
            'Key (file\/date-range identifier) of the first unfinished part - the one in flight or next up. Null when all parts are done or the worker has not started. URL keys (url_list sources) have their query string and userinfo redacted, since those can carry presigned tokens or credentials.'
        ),
    inflight_offset: zod
        .number()
        .nullable()
        .describe(
            'Committed byte offset (decompressed) within the in-flight part. Null when there is no in-flight part.'
        ),
    inflight_total_size: zod
        .number()
        .nullable()
        .describe(
            'Total decompressed size in bytes of the in-flight part, or null if the worker has not measured it yet.'
        ),
})

export type BatchImportPartsProgressApi = zod.input<typeof BatchImportPartsProgressApi>
export type BatchImportPartsProgressApiOutput = zod.output<typeof BatchImportPartsProgressApi>

export const batchImportSupportListApiBackoffAttemptMin = -2147483648
export const batchImportSupportListApiBackoffAttemptMax = 2147483647

export const batchImportSupportListApiCreatedByIdMin = -2147483648
export const batchImportSupportListApiCreatedByIdMax = 2147483647

export const BatchImportSupportListApi = zod
    .object({
        id: zod.uuid().describe('UUID of the batch import job.'),
        team_id: zod.number().describe('ID of the team (project) the import belongs to.'),
        team_name: zod.string().describe('Name of the team the import belongs to.'),
        status: BatchImportStatusEnumApi.optional().describe(
            'Raw persisted status of the job.\n\n\* `completed` - Completed\n\* `failed` - Failed\n\* `paused` - Paused\n\* `running` - Running'
        ),
        display_status: DisplayStatusEnumApi.describe(
            "Effective status: 'waiting_to_start' when the job is running but no worker has claimed it yet (lease_id is null), otherwise the raw status."
        ),
        status_message: zod
            .string()
            .nullable()
            .describe(
                'Developer-facing status message written by the worker or an operator - the primary debugging signal. Not shown to the customer. Embedded URLs have their query string and userinfo redacted, since url_list part keys can carry presigned tokens or credentials.'
            ),
        display_status_message: zod
            .string()
            .nullable()
            .describe(
                'Customer-facing status message shown in the PostHog UI. Embedded URLs are redacted the same way as status_message.'
            ),
        parts_progress: BatchImportPartsProgressApi.describe(
            'Worker part progress summary derived from the raw state blob.'
        ),
        source_type: zod
            .string()
            .describe(
                "Source the job imports from (e.g. s3, mixpanel, amplitude, urls, folder), or 'unknown' if unset."
            ),
        content_type: zod
            .string()
            .describe("Format of the source events (e.g. mixpanel, amplitude, captured), or 'unknown' if unset."),
        source_start_date: zod
            .string()
            .nullable()
            .describe('Start of the source date range for date-range sources (Mixpanel\/Amplitude), else null.'),
        source_end_date: zod
            .string()
            .nullable()
            .describe('End of the source date range for date-range sources (Mixpanel\/Amplitude), else null.'),
        sink_type: zod
            .string()
            .nullable()
            .describe(
                "Where imported events are written (normally 'capture'; 'kafka'\/'noop' for internal use), or null if unset."
            ),
        sink_send_rate: zod
            .number()
            .nullable()
            .describe('Configured sink send rate in events per second, or null if unset.'),
        lease_id: zod
            .string()
            .nullish()
            .describe(
                'Lease token of the worker currently holding the job, or null when unclaimed. Claims lease for 30 minutes; the running heartbeat renews for 5 minutes.'
            ),
        leased_until: zod.iso.datetime({ offset: true }).nullish().describe('When the current worker lease expires.'),
        lease_expired: zod
            .boolean()
            .describe(
                'True when the job holds a lease whose expiry is in the past. On a running job this means the worker died or the row is claimable again; the next poll can re-claim it.'
            ),
        backoff_attempt: zod
            .number()
            .min(batchImportSupportListApiBackoffAttemptMin)
            .max(batchImportSupportListApiBackoffAttemptMax)
            .optional()
            .describe('Consecutive transient-failure retries so far (0 = healthy).'),
        backoff_until: zod.iso
            .datetime({ offset: true })
            .nullish()
            .describe(
                'When the worker will retry after a transient failure. A future value means the job is in a retry loop, not stuck.'
            ),
        created_by_id: zod
            .number()
            .min(batchImportSupportListApiCreatedByIdMin)
            .max(batchImportSupportListApiCreatedByIdMax)
            .nullish()
            .describe('ID of the user who created the import, if any.'),
        created_at: zod.iso.datetime({ offset: true }).describe('When the import was created.'),
        updated_at: zod.iso
            .datetime({ offset: true })
            .describe('Last write to the row - the worker heartbeats this while processing.'),
    })
    .describe(
        'Compact cross-team diagnostics view of a batch import job for PostHog support staff.\n\nExcludes the raw `state` \/ `import_config` blobs (see the detail serializer) and never\nexposes the encrypted `secrets` column.'
    )

export type BatchImportSupportListApi = zod.input<typeof BatchImportSupportListApi>
export type BatchImportSupportListApiOutput = zod.output<typeof BatchImportSupportListApi>

export const PaginatedBatchImportSupportListListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(BatchImportSupportListApi),
})

export type PaginatedBatchImportSupportListListApi = zod.input<typeof PaginatedBatchImportSupportListListApi>
export type PaginatedBatchImportSupportListListApiOutput = zod.output<typeof PaginatedBatchImportSupportListListApi>

export const batchImportSupportDetailApiBackoffAttemptMin = -2147483648
export const batchImportSupportDetailApiBackoffAttemptMax = 2147483647

export const batchImportSupportDetailApiCreatedByIdMin = -2147483648
export const batchImportSupportDetailApiCreatedByIdMax = 2147483647

export const BatchImportSupportDetailApi = zod
    .object({
        id: zod.uuid().describe('UUID of the batch import job.'),
        team_id: zod.number().describe('ID of the team (project) the import belongs to.'),
        team_name: zod.string().describe('Name of the team the import belongs to.'),
        status: BatchImportStatusEnumApi.optional().describe(
            'Raw persisted status of the job.\n\n\* `completed` - Completed\n\* `failed` - Failed\n\* `paused` - Paused\n\* `running` - Running'
        ),
        display_status: DisplayStatusEnumApi.describe(
            "Effective status: 'waiting_to_start' when the job is running but no worker has claimed it yet (lease_id is null), otherwise the raw status."
        ),
        status_message: zod
            .string()
            .nullable()
            .describe(
                'Developer-facing status message written by the worker or an operator - the primary debugging signal. Not shown to the customer. Embedded URLs have their query string and userinfo redacted, since url_list part keys can carry presigned tokens or credentials.'
            ),
        display_status_message: zod
            .string()
            .nullable()
            .describe(
                'Customer-facing status message shown in the PostHog UI. Embedded URLs are redacted the same way as status_message.'
            ),
        parts_progress: BatchImportPartsProgressApi.describe(
            'Worker part progress summary derived from the raw state blob.'
        ),
        source_type: zod
            .string()
            .describe(
                "Source the job imports from (e.g. s3, mixpanel, amplitude, urls, folder), or 'unknown' if unset."
            ),
        content_type: zod
            .string()
            .describe("Format of the source events (e.g. mixpanel, amplitude, captured), or 'unknown' if unset."),
        source_start_date: zod
            .string()
            .nullable()
            .describe('Start of the source date range for date-range sources (Mixpanel\/Amplitude), else null.'),
        source_end_date: zod
            .string()
            .nullable()
            .describe('End of the source date range for date-range sources (Mixpanel\/Amplitude), else null.'),
        sink_type: zod
            .string()
            .nullable()
            .describe(
                "Where imported events are written (normally 'capture'; 'kafka'\/'noop' for internal use), or null if unset."
            ),
        sink_send_rate: zod
            .number()
            .nullable()
            .describe('Configured sink send rate in events per second, or null if unset.'),
        lease_id: zod
            .string()
            .nullish()
            .describe(
                'Lease token of the worker currently holding the job, or null when unclaimed. Claims lease for 30 minutes; the running heartbeat renews for 5 minutes.'
            ),
        leased_until: zod.iso.datetime({ offset: true }).nullish().describe('When the current worker lease expires.'),
        lease_expired: zod
            .boolean()
            .describe(
                'True when the job holds a lease whose expiry is in the past. On a running job this means the worker died or the row is claimable again; the next poll can re-claim it.'
            ),
        backoff_attempt: zod
            .number()
            .min(batchImportSupportDetailApiBackoffAttemptMin)
            .max(batchImportSupportDetailApiBackoffAttemptMax)
            .optional()
            .describe('Consecutive transient-failure retries so far (0 = healthy).'),
        backoff_until: zod.iso
            .datetime({ offset: true })
            .nullish()
            .describe(
                'When the worker will retry after a transient failure. A future value means the job is in a retry loop, not stuck.'
            ),
        created_by_id: zod
            .number()
            .min(batchImportSupportDetailApiCreatedByIdMin)
            .max(batchImportSupportDetailApiCreatedByIdMax)
            .nullish()
            .describe('ID of the user who created the import, if any.'),
        created_at: zod.iso.datetime({ offset: true }).describe('When the import was created.'),
        updated_at: zod.iso
            .datetime({ offset: true })
            .describe('Last write to the row - the worker heartbeats this while processing.'),
        state: zod
            .looseObject({})
            .nullable()
            .describe(
                "Raw worker progress blob: {'parts': [{'key', 'current_offset', 'total_size'}]}. A part is done when current_offset >= total_size; parts are processed in order. URL part keys (url_list sources) have their query string and userinfo redacted, since those can carry presigned tokens or credentials."
            ),
        import_config: zod
            .looseObject({})
            .nullable()
            .describe(
                'Source\/format\/sink configuration of the job. References secrets by key name only; secret values are never returned. Embedded URLs (e.g. a custom S3 endpoint_url) have their query string and userinfo redacted.'
            ),
        created_by_email: zod.string().nullable().describe('Email of the user who created the import, if known.'),
    })
    .describe(
        'Full diagnostics view: adds the raw worker `state` and `import_config` blobs.\n\n`import_config` holds secret key \*names\* only - secret values live exclusively in the\nencrypted `secrets` column, which no support serializer exposes.'
    )

export type BatchImportSupportDetailApi = zod.input<typeof BatchImportSupportDetailApi>
export type BatchImportSupportDetailApiOutput = zod.output<typeof BatchImportSupportDetailApi>

export const BatchImportApi = zod
    .object({
        id: zod.uuid(),
        team_id: zod.number(),
        created_at: zod.iso.datetime({ offset: true }),
        updated_at: zod.iso.datetime({ offset: true }),
        state: zod.unknown(),
        created_by: zod.looseObject({}).nullable(),
        status: BatchImportStatusEnumApi,
        display_status_message: zod.string().nullable(),
        import_config: zod.unknown(),
    })
    .describe('Serializer for BatchImport model')

export type BatchImportApi = zod.input<typeof BatchImportApi>
export type BatchImportApiOutput = zod.output<typeof BatchImportApi>

export const PaginatedBatchImportListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(BatchImportApi),
})

export type PaginatedBatchImportListApi = zod.input<typeof PaginatedBatchImportListApi>
export type PaginatedBatchImportListApiOutput = zod.output<typeof PaginatedBatchImportListApi>

export const PatchedBatchImportApi = zod
    .object({
        id: zod.uuid().optional(),
        team_id: zod.number().optional(),
        created_at: zod.iso.datetime({ offset: true }).optional(),
        updated_at: zod.iso.datetime({ offset: true }).optional(),
        state: zod.unknown().optional(),
        created_by: zod.looseObject({}).nullish(),
        status: BatchImportStatusEnumApi.optional(),
        display_status_message: zod.string().nullish(),
        import_config: zod.unknown().optional(),
    })
    .describe('Serializer for BatchImport model')

export type PatchedBatchImportApi = zod.input<typeof PatchedBatchImportApi>
export type PatchedBatchImportApiOutput = zod.output<typeof PatchedBatchImportApi>

export const BatchImportResponseApi = zod
    .object({
        id: zod.uuid(),
        source_type: zod.string(),
        content_type: zod.string(),
        status: BatchImportStatusEnumApi.optional(),
        display_status: zod.string(),
        start_date: zod.string().nullable(),
        end_date: zod.string().nullable(),
        created_by: zod.looseObject({}).nullable(),
        created_at: zod.iso.datetime({ offset: true }),
        status_message: zod.string().nullable(),
        state: zod.unknown().optional(),
        is_trial: zod
            .boolean()
            .describe('Whether this job is a trial run (stores browsable results instead of ingesting).'),
        trial_record_limit: zod.number().nullable(),
        promoted_from_trial_id: zod.string().nullable(),
    })
    .describe('Serializer for BatchImport responses that matches frontend expectations')

export type BatchImportResponseApi = zod.input<typeof BatchImportResponseApi>
export type BatchImportResponseApiOutput = zod.output<typeof BatchImportResponseApi>

export const TrialRecordsResponseApi = zod
    .object({
        records: zod
            .array(zod.unknown())
            .describe(
                'Trial records in source order: each has seq (global index), source (the original source event), outputs (the event(s) it would produce), and error (why it would be dropped, if it would be).'
            ),
        page: zod.number().describe('Zero-based index of this page.'),
        total_pages: zod.number().describe('Number of result pages written so far.'),
        total_records: zod.number().describe('Number of source records processed so far.'),
        summary: zod
            .unknown()
            .describe(
                'Running aggregates: output event name counts, error counts, dropped\/skipped totals, timestamp range.'
            ),
    })
    .describe('One page of trial-run results, proxied from the trial output store.')

export type TrialRecordsResponseApi = zod.input<typeof TrialRecordsResponseApi>
export type TrialRecordsResponseApiOutput = zod.output<typeof TrialRecordsResponseApi>

export const BatchImportAWSIAMSetupApi = zod
    .object({
        available: zod.boolean().describe('Whether IAM role authentication is available on this PostHog deployment.'),
        external_id: zod
            .string()
            .describe("External ID to pin in the role trust policy's sts:ExternalId condition. Stable per project."),
        posthog_role_arn: zod.string().describe("ARN of PostHog's import role -- the principal your role must trust."),
        trust_policy: zod.string().describe('Ready-to-paste IAM trust policy JSON for the role in your AWS account.'),
        permission_policy_template: zod
            .string()
            .describe('IAM permission policy JSON template; replace YOUR_BUCKET and YOUR_PREFIX with your values.'),
    })
    .describe('Values a customer needs to configure cross-account IAM role access for S3 imports.')

export type BatchImportAWSIAMSetupApi = zod.input<typeof BatchImportAWSIAMSetupApi>
export type BatchImportAWSIAMSetupApiOutput = zod.output<typeof BatchImportAWSIAMSetupApi>
