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

export const ErrorTrackingAssignmentRulesCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export const ErrorTrackingAssignmentRulesUpdateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export const ErrorTrackingAssignmentRulesPartialUpdateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export const errorTrackingAssignmentRulesReorderPartialUpdateBodyOrderKeyMin = -2147483648
export const errorTrackingAssignmentRulesReorderPartialUpdateBodyOrderKeyMax = 2147483647

export const ErrorTrackingAssignmentRulesReorderPartialUpdateBody = /* @__PURE__ */ zod.object({
    filters: zod.unknown().optional(),
    order_key: zod
        .number()
        .min(errorTrackingAssignmentRulesReorderPartialUpdateBodyOrderKeyMin)
        .max(errorTrackingAssignmentRulesReorderPartialUpdateBodyOrderKeyMax)
        .optional(),
    disabled_data: zod.unknown().nullish(),
})

export const ErrorTrackingExternalReferencesCreateBody = /* @__PURE__ */ zod.object({
    integration_id: zod.number(),
    config: zod.unknown(),
    issue: zod.uuid(),
})

export const ErrorTrackingGroupingRulesCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export const errorTrackingGroupingRulesUpdateBodyOrderKeyMin = -2147483648
export const errorTrackingGroupingRulesUpdateBodyOrderKeyMax = 2147483647

export const ErrorTrackingGroupingRulesUpdateBody = /* @__PURE__ */ zod.object({
    filters: zod.unknown(),
    description: zod.string().nullish(),
    order_key: zod
        .number()
        .min(errorTrackingGroupingRulesUpdateBodyOrderKeyMin)
        .max(errorTrackingGroupingRulesUpdateBodyOrderKeyMax),
    disabled_data: zod.unknown().nullish(),
})

export const errorTrackingGroupingRulesPartialUpdateBodyOrderKeyMin = -2147483648
export const errorTrackingGroupingRulesPartialUpdateBodyOrderKeyMax = 2147483647

export const ErrorTrackingGroupingRulesPartialUpdateBody = /* @__PURE__ */ zod.object({
    filters: zod.unknown().optional(),
    description: zod.string().nullish(),
    order_key: zod
        .number()
        .min(errorTrackingGroupingRulesPartialUpdateBodyOrderKeyMin)
        .max(errorTrackingGroupingRulesPartialUpdateBodyOrderKeyMax)
        .optional(),
    disabled_data: zod.unknown().nullish(),
})

export const errorTrackingGroupingRulesReorderPartialUpdateBodyOrderKeyMin = -2147483648
export const errorTrackingGroupingRulesReorderPartialUpdateBodyOrderKeyMax = 2147483647

export const ErrorTrackingGroupingRulesReorderPartialUpdateBody = /* @__PURE__ */ zod.object({
    filters: zod.unknown().optional(),
    description: zod.string().nullish(),
    order_key: zod
        .number()
        .min(errorTrackingGroupingRulesReorderPartialUpdateBodyOrderKeyMin)
        .max(errorTrackingGroupingRulesReorderPartialUpdateBodyOrderKeyMax)
        .optional(),
    disabled_data: zod.unknown().nullish(),
})

export const ErrorTrackingIssuesCreateBody = /* @__PURE__ */ zod.object({
    status: zod
        .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed'])
        .optional()
        .describe(
            '* `archived` - Archived\n* `active` - Active\n* `resolved` - Resolved\n* `pending_release` - Pending release\n* `suppressed` - Suppressed'
        ),
    name: zod.string().nullish(),
    description: zod.string().nullish(),
    first_seen: zod.iso.datetime({}),
    assignee: zod.object({
        id: zod.union([zod.number(), zod.string()]).nullable(),
        type: zod.string(),
    }),
    external_issues: zod.array(
        zod.object({
            id: zod.uuid(),
            integration: zod.object({
                id: zod.number(),
                kind: zod.string(),
                display_name: zod.string(),
            }),
            integration_id: zod.number(),
            config: zod.unknown(),
            issue: zod.uuid(),
            external_url: zod.string(),
        })
    ),
})

export const ErrorTrackingIssuesUpdateBody = /* @__PURE__ */ zod.object({
    status: zod
        .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed'])
        .optional()
        .describe(
            '* `archived` - Archived\n* `active` - Active\n* `resolved` - Resolved\n* `pending_release` - Pending release\n* `suppressed` - Suppressed'
        ),
    name: zod.string().nullish(),
    description: zod.string().nullish(),
    first_seen: zod.iso.datetime({}),
    assignee: zod.object({
        id: zod.union([zod.number(), zod.string()]).nullable(),
        type: zod.string(),
    }),
    external_issues: zod.array(
        zod.object({
            id: zod.uuid(),
            integration: zod.object({
                id: zod.number(),
                kind: zod.string(),
                display_name: zod.string(),
            }),
            integration_id: zod.number(),
            config: zod.unknown(),
            issue: zod.uuid(),
            external_url: zod.string(),
        })
    ),
})

export const ErrorTrackingIssuesPartialUpdateBody = /* @__PURE__ */ zod.object({
    status: zod
        .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed'])
        .optional()
        .describe(
            '* `archived` - Archived\n* `active` - Active\n* `resolved` - Resolved\n* `pending_release` - Pending release\n* `suppressed` - Suppressed'
        ),
    name: zod.string().nullish(),
    description: zod.string().nullish(),
    first_seen: zod.iso.datetime({}).optional(),
    assignee: zod
        .object({
            id: zod.union([zod.number(), zod.string()]).nullable(),
            type: zod.string(),
        })
        .optional(),
    external_issues: zod
        .array(
            zod.object({
                id: zod.uuid(),
                integration: zod.object({
                    id: zod.number(),
                    kind: zod.string(),
                    display_name: zod.string(),
                }),
                integration_id: zod.number(),
                config: zod.unknown(),
                issue: zod.uuid(),
                external_url: zod.string(),
            })
        )
        .optional(),
})

export const ErrorTrackingIssuesAssignPartialUpdateBody = /* @__PURE__ */ zod.object({
    status: zod
        .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed'])
        .optional()
        .describe(
            '* `archived` - Archived\n* `active` - Active\n* `resolved` - Resolved\n* `pending_release` - Pending release\n* `suppressed` - Suppressed'
        ),
    name: zod.string().nullish(),
    description: zod.string().nullish(),
    first_seen: zod.iso.datetime({}).optional(),
    assignee: zod
        .object({
            id: zod.union([zod.number(), zod.string()]).nullable(),
            type: zod.string(),
        })
        .optional(),
    external_issues: zod
        .array(
            zod.object({
                id: zod.uuid(),
                integration: zod.object({
                    id: zod.number(),
                    kind: zod.string(),
                    display_name: zod.string(),
                }),
                integration_id: zod.number(),
                config: zod.unknown(),
                issue: zod.uuid(),
                external_url: zod.string(),
            })
        )
        .optional(),
})

export const ErrorTrackingIssuesCohortUpdateBody = /* @__PURE__ */ zod.object({
    status: zod
        .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed'])
        .optional()
        .describe(
            '* `archived` - Archived\n* `active` - Active\n* `resolved` - Resolved\n* `pending_release` - Pending release\n* `suppressed` - Suppressed'
        ),
    name: zod.string().nullish(),
    description: zod.string().nullish(),
    first_seen: zod.iso.datetime({}),
    assignee: zod.object({
        id: zod.union([zod.number(), zod.string()]).nullable(),
        type: zod.string(),
    }),
    external_issues: zod.array(
        zod.object({
            id: zod.uuid(),
            integration: zod.object({
                id: zod.number(),
                kind: zod.string(),
                display_name: zod.string(),
            }),
            integration_id: zod.number(),
            config: zod.unknown(),
            issue: zod.uuid(),
            external_url: zod.string(),
        })
    ),
})

export const ErrorTrackingIssuesMergeCreateBody = /* @__PURE__ */ zod.object({
    ids: zod.array(zod.uuid()).describe('IDs of the issues to merge into the current issue.'),
})

export const ErrorTrackingIssuesSplitCreateBody = /* @__PURE__ */ zod.object({
    fingerprints: zod
        .array(
            zod.object({
                fingerprint: zod.string().describe('Fingerprint to split into a new issue.'),
                name: zod
                    .string()
                    .optional()
                    .describe('Optional name for the new issue created from this fingerprint.'),
                description: zod
                    .string()
                    .optional()
                    .describe('Optional description for the new issue created from this fingerprint.'),
            })
        )
        .optional()
        .describe('Fingerprints to split into new issues. Each fingerprint becomes its own new issue.'),
})

export const ErrorTrackingIssuesBulkCreateBody = /* @__PURE__ */ zod.object({
    status: zod
        .enum(['archived', 'active', 'resolved', 'pending_release', 'suppressed'])
        .optional()
        .describe(
            '* `archived` - Archived\n* `active` - Active\n* `resolved` - Resolved\n* `pending_release` - Pending release\n* `suppressed` - Suppressed'
        ),
    name: zod.string().nullish(),
    description: zod.string().nullish(),
    first_seen: zod.iso.datetime({}),
    assignee: zod.object({
        id: zod.union([zod.number(), zod.string()]).nullable(),
        type: zod.string(),
    }),
    external_issues: zod.array(
        zod.object({
            id: zod.uuid(),
            integration: zod.object({
                id: zod.number(),
                kind: zod.string(),
                display_name: zod.string(),
            }),
            integration_id: zod.number(),
            config: zod.unknown(),
            issue: zod.uuid(),
            external_url: zod.string(),
        })
    ),
})

export const ErrorTrackingSettingsUpdateSettingsPartialUpdateBody = /* @__PURE__ */ zod.object({
    project_rate_limit_value: zod
        .number()
        .min(1)
        .nullish()
        .describe(
            'Maximum number of exception events ingested per bucket for the entire project. Null removes the limit.'
        ),
    project_rate_limit_bucket_size_minutes: zod
        .number()
        .min(1)
        .nullish()
        .describe('Bucket window over which the project-wide rate limit applies, in minutes.'),
})

export const ErrorTrackingSpikeDetectionConfigUpdateConfigPartialUpdateBody = /* @__PURE__ */ zod.object({
    snooze_duration_minutes: zod
        .number()
        .min(1)
        .optional()
        .describe('Time to wait before alerting again for the same issue after a spike is detected.'),
    multiplier: zod
        .number()
        .min(1)
        .optional()
        .describe('The factor by which the current exception count must exceed the baseline to be considered a spike.'),
    threshold: zod
        .number()
        .min(1)
        .optional()
        .describe('The minimum number of exceptions required in a 5-minute window before a spike can be detected.'),
})

export const ErrorTrackingStackFramesBatchGetCreateBody = /* @__PURE__ */ zod.object({
    contents: zod.unknown(),
    resolved: zod.boolean(),
    context: zod.unknown().nullish(),
    symbol_set_ref: zod.string().optional(),
})

export const ErrorTrackingSuppressionRulesCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export const errorTrackingSuppressionRulesUpdateBodyOrderKeyMin = -2147483648
export const errorTrackingSuppressionRulesUpdateBodyOrderKeyMax = 2147483647

export const ErrorTrackingSuppressionRulesUpdateBody = /* @__PURE__ */ zod.object({
    filters: zod.unknown(),
    order_key: zod
        .number()
        .min(errorTrackingSuppressionRulesUpdateBodyOrderKeyMin)
        .max(errorTrackingSuppressionRulesUpdateBodyOrderKeyMax),
    disabled_data: zod.unknown().nullish(),
    sampling_rate: zod.number().optional(),
})

export const errorTrackingSuppressionRulesPartialUpdateBodyOrderKeyMin = -2147483648
export const errorTrackingSuppressionRulesPartialUpdateBodyOrderKeyMax = 2147483647

export const ErrorTrackingSuppressionRulesPartialUpdateBody = /* @__PURE__ */ zod.object({
    filters: zod.unknown().optional(),
    order_key: zod
        .number()
        .min(errorTrackingSuppressionRulesPartialUpdateBodyOrderKeyMin)
        .max(errorTrackingSuppressionRulesPartialUpdateBodyOrderKeyMax)
        .optional(),
    disabled_data: zod.unknown().nullish(),
    sampling_rate: zod.number().optional(),
})

export const errorTrackingSuppressionRulesReorderPartialUpdateBodyOrderKeyMin = -2147483648
export const errorTrackingSuppressionRulesReorderPartialUpdateBodyOrderKeyMax = 2147483647

export const ErrorTrackingSuppressionRulesReorderPartialUpdateBody = /* @__PURE__ */ zod.object({
    filters: zod.unknown().optional(),
    order_key: zod
        .number()
        .min(errorTrackingSuppressionRulesReorderPartialUpdateBodyOrderKeyMin)
        .max(errorTrackingSuppressionRulesReorderPartialUpdateBodyOrderKeyMax)
        .optional(),
    disabled_data: zod.unknown().nullish(),
    sampling_rate: zod.number().optional(),
})

export const ErrorTrackingReleasesCreateBody = /* @__PURE__ */ zod.object({
    hash_id: zod.string(),
    metadata: zod.unknown().nullish(),
    version: zod.string(),
    project: zod.string(),
})

export const ErrorTrackingReleasesUpdateBody = /* @__PURE__ */ zod.object({
    hash_id: zod.string(),
    metadata: zod.unknown().nullish(),
    version: zod.string(),
    project: zod.string(),
})

export const ErrorTrackingReleasesPartialUpdateBody = /* @__PURE__ */ zod.object({
    hash_id: zod.string().optional(),
    metadata: zod.unknown().nullish(),
    version: zod.string().optional(),
    project: zod.string().optional(),
})

export const ErrorTrackingSymbolSetsCreateBody = /* @__PURE__ */ zod.object({})

export const ErrorTrackingSymbolSetsUpdateBody = /* @__PURE__ */ zod.object({})

export const ErrorTrackingSymbolSetsPartialUpdateBody = /* @__PURE__ */ zod.object({})

export const ErrorTrackingSymbolSetsFinishUploadUpdateBody = /* @__PURE__ */ zod.object({
    content_hash: zod.string().describe('Hash of the uploaded symbol set content.'),
})

export const ErrorTrackingSymbolSetsBulkDeleteCreateBody = /* @__PURE__ */ zod.object({
    ids: zod.array(zod.uuid()).describe('Symbol set IDs to delete.'),
})

export const ErrorTrackingSymbolSetsBulkFinishUploadCreateBody = /* @__PURE__ */ zod.object({
    content_hashes: zod.record(zod.string(), zod.string()).describe('Map of symbol set ID to uploaded content hash.'),
})

export const errorTrackingSymbolSetsBulkStartUploadCreateBodyForceDefault = false

export const ErrorTrackingSymbolSetsBulkStartUploadCreateBody = /* @__PURE__ */ zod.object({
    chunk_ids: zod
        .array(zod.string())
        .optional()
        .describe('Legacy list of symbol set references to upload, all associated with `release_id`.'),
    release_id: zod.string().nullish().describe('Optional error tracking release ID used with `chunk_ids`.'),
    symbol_sets: zod
        .array(
            zod.object({
                chunk_id: zod.string().describe('Symbol set reference to upload.'),
                release_id: zod
                    .string()
                    .nullish()
                    .describe('Optional error tracking release ID associated with this symbol set.'),
                content_hash: zod
                    .string()
                    .nullish()
                    .describe('Optional hash of the symbol set content, used to skip unchanged uploads.'),
            })
        )
        .optional()
        .describe('Symbol sets to upload with per-symbol release IDs and content hashes.'),
    force: zod
        .boolean()
        .default(errorTrackingSymbolSetsBulkStartUploadCreateBodyForceDefault)
        .describe('Whether to overwrite uploaded symbol sets whose content hash changed.'),
})

export const ErrorTrackingSymbolSetsStartUploadCreateBody = /* @__PURE__ */ zod.object({})
