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

export const ConversionGoalSummaryApi = zod.object({
    id: zod.string().describe('Unique id of the goal (event name, action id, or DW goal id)'),
    name: zod.string().describe('Display name of the conversion goal'),
    kind: zod
        .string()
        .describe(
            'Goal type — one of: EventsNode (PostHog event), ActionsNode (PostHog action), DataWarehouseNode (external table)'
        ),
    target_label: zod.string().describe('Human-readable target the goal matches (event\/action name or table)'),
    last_30d_count: zod.number().describe('Count of matching conversion events in the last 30 days'),
    integrated_count: zod
        .number()
        .nullable()
        .describe('Conversions whose utm_source matches a known integration. Null for DataWarehouseNode goals.'),
    events_without_utm_source: zod
        .number()
        .nullable()
        .describe('Conversions with no utm_source at all (fix by tagging UTMs). Null for DataWarehouseNode goals.'),
    events_with_unmatched_utm_source: zod
        .number()
        .nullable()
        .describe(
            'Conversions with a utm_source that matches no integration (fix with custom_source_mappings). Null for DataWarehouseNode goals.'
        ),
    non_integrated_count: zod
        .number()
        .nullable()
        .describe(
            'Total non-integrated conversions (without + unmatched utm_source). Null for DataWarehouseNode goals.'
        ),
    integrated_pct: zod
        .number()
        .nullable()
        .describe('Percentage of conversions that are integrated. Null for DataWarehouseNode goals.'),
    is_misconfigured: zod.boolean().describe('Whether the goal could not be evaluated (e.g. deleted action)'),
    misconfig_reason: zod.string().nullable().describe('Explanation when is_misconfigured is true'),
    is_approximate: zod
        .boolean()
        .describe("True when this 30d count may differ from the dashboard's attribution-windowed number"),
    approximation_reason: zod.string().nullable().describe('Explanation when is_approximate is true'),
})

export type ConversionGoalSummaryApi = zod.input<typeof ConversionGoalSummaryApi>
export type ConversionGoalSummaryApiOutput = zod.output<typeof ConversionGoalSummaryApi>

export const ConversionGoalsListResponseApi = zod.object({
    goals: zod
        .array(
            zod.object({
                id: zod.string().describe('Unique id of the goal (event name, action id, or DW goal id)'),
                name: zod.string().describe('Display name of the conversion goal'),
                kind: zod
                    .string()
                    .describe(
                        'Goal type — one of: EventsNode (PostHog event), ActionsNode (PostHog action), DataWarehouseNode (external table)'
                    ),
                target_label: zod
                    .string()
                    .describe('Human-readable target the goal matches (event\/action name or table)'),
                last_30d_count: zod.number().describe('Count of matching conversion events in the last 30 days'),
                integrated_count: zod
                    .number()
                    .nullable()
                    .describe(
                        'Conversions whose utm_source matches a known integration. Null for DataWarehouseNode goals.'
                    ),
                events_without_utm_source: zod
                    .number()
                    .nullable()
                    .describe(
                        'Conversions with no utm_source at all (fix by tagging UTMs). Null for DataWarehouseNode goals.'
                    ),
                events_with_unmatched_utm_source: zod
                    .number()
                    .nullable()
                    .describe(
                        'Conversions with a utm_source that matches no integration (fix with custom_source_mappings). Null for DataWarehouseNode goals.'
                    ),
                non_integrated_count: zod
                    .number()
                    .nullable()
                    .describe(
                        'Total non-integrated conversions (without + unmatched utm_source). Null for DataWarehouseNode goals.'
                    ),
                integrated_pct: zod
                    .number()
                    .nullable()
                    .describe('Percentage of conversions that are integrated. Null for DataWarehouseNode goals.'),
                is_misconfigured: zod
                    .boolean()
                    .describe('Whether the goal could not be evaluated (e.g. deleted action)'),
                misconfig_reason: zod.string().nullable().describe('Explanation when is_misconfigured is true'),
                is_approximate: zod
                    .boolean()
                    .describe("True when this 30d count may differ from the dashboard's attribution-windowed number"),
                approximation_reason: zod.string().nullable().describe('Explanation when is_approximate is true'),
            })
        )
        .describe('One summary entry per configured conversion goal'),
    attribution_window_days: zod.number().describe("The team's configured attribution window in days"),
    attribution_mode: zod.string().describe("The team's attribution model (e.g. last_touch, first_touch, linear)"),
    has_misconfigured: zod.boolean().describe('True if any goal is misconfigured'),
})

export type ConversionGoalsListResponseApi = zod.input<typeof ConversionGoalsListResponseApi>
export type ConversionGoalsListResponseApiOutput = zod.output<typeof ConversionGoalsListResponseApi>

export const RequiredTableStatusApi = zod.object({
    table_name: zod.string().describe("Name of the required source table (e.g. 'campaign', 'campaign_stats')"),
    present: zod.boolean().describe('Whether the table exists as a schema on the connected source'),
    should_sync: zod.boolean().describe('Whether the table is enabled for sync'),
    status: zod
        .string()
        .nullable()
        .describe('ExternalDataSchema status: Completed\/Running\/Failed\/Paused\/Cancelled, or null'),
    last_synced_at: zod.iso.datetime({ offset: true }).nullable().describe('When this table last completed a sync'),
})

export type RequiredTableStatusApi = zod.input<typeof RequiredTableStatusApi>
export type RequiredTableStatusApiOutput = zod.output<typeof RequiredTableStatusApi>

export const DataSourceHealthEntryApi = zod.object({
    source_type: zod.string().describe("External data source type key (e.g. 'GoogleAds', 'MetaAds')"),
    is_native: zod.boolean().describe('Whether this is a native marketing integration'),
    display_name: zod.string().describe("Human-readable integration name (e.g. 'Google Ads')"),
    connected: zod.boolean().describe('Whether a live source of this type is connected'),
    last_sync_at: zod.iso.datetime({ offset: true }).nullable().describe('When the source last completed a sync'),
    last_sync_status: zod.string().describe('Sync status: ok\/error\/stale\/tables_failed\/not_connected\/never'),
    last_error: zod.string().nullable().describe('Latest unresolved sync error message, if any'),
    rows_last_24h: zod.number().describe('Rows synced in the last 24 hours'),
    rows_last_7d: zod.number().describe('Rows synced in the last 7 days'),
    sources_map_present: zod.boolean().describe('Whether a column mapping exists for this source'),
    schema_columns_mapped: zod.array(zod.string()).describe('Schema columns currently mapped for this source'),
    schema_columns_required_missing: zod
        .array(zod.string())
        .describe('Required schema columns that are not yet mapped'),
    required_tables: zod
        .array(
            zod.object({
                table_name: zod
                    .string()
                    .describe("Name of the required source table (e.g. 'campaign', 'campaign_stats')"),
                present: zod.boolean().describe('Whether the table exists as a schema on the connected source'),
                should_sync: zod.boolean().describe('Whether the table is enabled for sync'),
                status: zod
                    .string()
                    .nullable()
                    .describe('ExternalDataSchema status: Completed\/Running\/Failed\/Paused\/Cancelled, or null'),
                last_synced_at: zod.iso
                    .datetime({ offset: true })
                    .nullable()
                    .describe('When this table last completed a sync'),
            })
        )
        .describe('Per-required-table sync status for this integration'),
    settings_url: zod.string().describe('URL to the Marketing analytics global settings page'),
    schemas_url: zod.string().nullable().describe('URL to the per-source Schemas tab, or null if not connected'),
    diagnosis: zod.string().describe("Human-readable diagnosis of this source's health"),
    fix_suggestion: zod.string().nullable().describe('Suggested fix when the source is unhealthy'),
})

export type DataSourceHealthEntryApi = zod.input<typeof DataSourceHealthEntryApi>
export type DataSourceHealthEntryApiOutput = zod.output<typeof DataSourceHealthEntryApi>

export const DataSourceHealthResponseApi = zod.object({
    integrations: zod
        .array(
            zod.object({
                source_type: zod.string().describe("External data source type key (e.g. 'GoogleAds', 'MetaAds')"),
                is_native: zod.boolean().describe('Whether this is a native marketing integration'),
                display_name: zod.string().describe("Human-readable integration name (e.g. 'Google Ads')"),
                connected: zod.boolean().describe('Whether a live source of this type is connected'),
                last_sync_at: zod.iso
                    .datetime({ offset: true })
                    .nullable()
                    .describe('When the source last completed a sync'),
                last_sync_status: zod
                    .string()
                    .describe('Sync status: ok\/error\/stale\/tables_failed\/not_connected\/never'),
                last_error: zod.string().nullable().describe('Latest unresolved sync error message, if any'),
                rows_last_24h: zod.number().describe('Rows synced in the last 24 hours'),
                rows_last_7d: zod.number().describe('Rows synced in the last 7 days'),
                sources_map_present: zod.boolean().describe('Whether a column mapping exists for this source'),
                schema_columns_mapped: zod
                    .array(zod.string())
                    .describe('Schema columns currently mapped for this source'),
                schema_columns_required_missing: zod
                    .array(zod.string())
                    .describe('Required schema columns that are not yet mapped'),
                required_tables: zod
                    .array(
                        zod.object({
                            table_name: zod
                                .string()
                                .describe("Name of the required source table (e.g. 'campaign', 'campaign_stats')"),
                            present: zod
                                .boolean()
                                .describe('Whether the table exists as a schema on the connected source'),
                            should_sync: zod.boolean().describe('Whether the table is enabled for sync'),
                            status: zod
                                .string()
                                .nullable()
                                .describe(
                                    'ExternalDataSchema status: Completed\/Running\/Failed\/Paused\/Cancelled, or null'
                                ),
                            last_synced_at: zod.iso
                                .datetime({ offset: true })
                                .nullable()
                                .describe('When this table last completed a sync'),
                        })
                    )
                    .describe('Per-required-table sync status for this integration'),
                settings_url: zod.string().describe('URL to the Marketing analytics global settings page'),
                schemas_url: zod
                    .string()
                    .nullable()
                    .describe('URL to the per-source Schemas tab, or null if not connected'),
                diagnosis: zod.string().describe("Human-readable diagnosis of this source's health"),
                fix_suggestion: zod.string().nullable().describe('Suggested fix when the source is unhealthy'),
            })
        )
        .describe('One health entry per native integration'),
    has_any_data: zod.boolean().describe('True if any integration synced rows in the last 7 days'),
    overall_status: zod.string().describe('Overall: healthy\/degraded\/broken\/no_sources'),
    issues_summary: zod.array(zod.string()).describe('Short human-readable summary of detected issues'),
})

export type DataSourceHealthResponseApi = zod.input<typeof DataSourceHealthResponseApi>
export type DataSourceHealthResponseApiOutput = zod.output<typeof DataSourceHealthResponseApi>

export const UnmatchedUtmSampleApi = zod.object({
    raw_value: zod.string().describe("A raw utm_source value that doesn't match the integration exactly"),
    event_count: zod.number().describe('Number of events with this raw value in the window'),
    suggested_integration: zod.string().nullable().describe('Integration suggested by token match, if any'),
})

export type UnmatchedUtmSampleApi = zod.input<typeof UnmatchedUtmSampleApi>
export type UnmatchedUtmSampleApiOutput = zod.output<typeof UnmatchedUtmSampleApi>

export const AttributionHealthEntryApi = zod.object({
    integration_key: zod.string().describe("Integration key (e.g. 'google', 'meta')"),
    display_name: zod.string().describe('Human-readable integration name'),
    events_with_utm_last_7d: zod.number().describe('Total events with any utm_source in the window'),
    events_matched_last_7d: zod.number().describe('Events whose utm_source matched this integration'),
    events_unmatched_likely_yours_last_7d: zod
        .number()
        .describe("Events that look like this integration's but don't match exactly"),
    last_event_with_matching_utm_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('Timestamp of the most recent matched event'),
    matched_pct: zod.number().describe('Percentage of UTM events matched to this integration'),
    sample_unmatched_utm_sources: zod
        .array(
            zod.object({
                raw_value: zod.string().describe("A raw utm_source value that doesn't match the integration exactly"),
                event_count: zod.number().describe('Number of events with this raw value in the window'),
                suggested_integration: zod.string().nullable().describe('Integration suggested by token match, if any'),
            })
        )
        .describe('Sample of likely-yours unmatched utm_source values'),
})

export type AttributionHealthEntryApi = zod.input<typeof AttributionHealthEntryApi>
export type AttributionHealthEntryApiOutput = zod.output<typeof AttributionHealthEntryApi>

export const RecommendedActionApi = zod.object({
    title: zod.string().describe('Short title of the recommended action'),
    detail: zod.string().describe('Detailed explanation of the action'),
    severity: zod.string().describe('Action severity'),
    target_tool: zod.string().nullable().describe('Follow-up tool to call next, if any'),
})

export type RecommendedActionApi = zod.input<typeof RecommendedActionApi>
export type RecommendedActionApiOutput = zod.output<typeof RecommendedActionApi>

export const IntegrationDiagnosticApi = zod.object({
    integration_key: zod.string().describe("Integration key (e.g. 'google', 'meta')"),
    source_type: zod.string().describe("External data source type key (e.g. 'GoogleAds')"),
    display_name: zod.string().describe('Human-readable integration name'),
    overall_status: zod.string().describe('Per-integration status'),
    diagnosis: zod.string().describe('Human-readable cross-domain diagnosis'),
    data_source: zod
        .union([
            zod.object({
                source_type: zod.string().describe("External data source type key (e.g. 'GoogleAds', 'MetaAds')"),
                is_native: zod.boolean().describe('Whether this is a native marketing integration'),
                display_name: zod.string().describe("Human-readable integration name (e.g. 'Google Ads')"),
                connected: zod.boolean().describe('Whether a live source of this type is connected'),
                last_sync_at: zod.iso
                    .datetime({ offset: true })
                    .nullable()
                    .describe('When the source last completed a sync'),
                last_sync_status: zod
                    .string()
                    .describe('Sync status: ok\/error\/stale\/tables_failed\/not_connected\/never'),
                last_error: zod.string().nullable().describe('Latest unresolved sync error message, if any'),
                rows_last_24h: zod.number().describe('Rows synced in the last 24 hours'),
                rows_last_7d: zod.number().describe('Rows synced in the last 7 days'),
                sources_map_present: zod.boolean().describe('Whether a column mapping exists for this source'),
                schema_columns_mapped: zod
                    .array(zod.string())
                    .describe('Schema columns currently mapped for this source'),
                schema_columns_required_missing: zod
                    .array(zod.string())
                    .describe('Required schema columns that are not yet mapped'),
                required_tables: zod
                    .array(
                        zod.object({
                            table_name: zod
                                .string()
                                .describe("Name of the required source table (e.g. 'campaign', 'campaign_stats')"),
                            present: zod
                                .boolean()
                                .describe('Whether the table exists as a schema on the connected source'),
                            should_sync: zod.boolean().describe('Whether the table is enabled for sync'),
                            status: zod
                                .string()
                                .nullable()
                                .describe(
                                    'ExternalDataSchema status: Completed\/Running\/Failed\/Paused\/Cancelled, or null'
                                ),
                            last_synced_at: zod.iso
                                .datetime({ offset: true })
                                .nullable()
                                .describe('When this table last completed a sync'),
                        })
                    )
                    .describe('Per-required-table sync status for this integration'),
                settings_url: zod.string().describe('URL to the Marketing analytics global settings page'),
                schemas_url: zod
                    .string()
                    .nullable()
                    .describe('URL to the per-source Schemas tab, or null if not connected'),
                diagnosis: zod.string().describe("Human-readable diagnosis of this source's health"),
                fix_suggestion: zod.string().nullable().describe('Suggested fix when the source is unhealthy'),
            }),
            zod.null(),
        ])
        .optional()
        .describe('Data-source (sync) side health, or null if not connected'),
    attribution: zod
        .union([
            zod.object({
                integration_key: zod.string().describe("Integration key (e.g. 'google', 'meta')"),
                display_name: zod.string().describe('Human-readable integration name'),
                events_with_utm_last_7d: zod.number().describe('Total events with any utm_source in the window'),
                events_matched_last_7d: zod.number().describe('Events whose utm_source matched this integration'),
                events_unmatched_likely_yours_last_7d: zod
                    .number()
                    .describe("Events that look like this integration's but don't match exactly"),
                last_event_with_matching_utm_at: zod.iso
                    .datetime({ offset: true })
                    .nullable()
                    .describe('Timestamp of the most recent matched event'),
                matched_pct: zod.number().describe('Percentage of UTM events matched to this integration'),
                sample_unmatched_utm_sources: zod
                    .array(
                        zod.object({
                            raw_value: zod
                                .string()
                                .describe("A raw utm_source value that doesn't match the integration exactly"),
                            event_count: zod.number().describe('Number of events with this raw value in the window'),
                            suggested_integration: zod
                                .string()
                                .nullable()
                                .describe('Integration suggested by token match, if any'),
                        })
                    )
                    .describe('Sample of likely-yours unmatched utm_source values'),
            }),
            zod.null(),
        ])
        .optional()
        .describe('Attribution (UTM events) side health, or null if no data'),
    recommended_actions: zod
        .array(
            zod.object({
                title: zod.string().describe('Short title of the recommended action'),
                detail: zod.string().describe('Detailed explanation of the action'),
                severity: zod.string().describe('Action severity'),
                target_tool: zod.string().nullable().describe('Follow-up tool to call next, if any'),
            })
        )
        .describe('Recommended next steps for this integration'),
})

export type IntegrationDiagnosticApi = zod.input<typeof IntegrationDiagnosticApi>
export type IntegrationDiagnosticApiOutput = zod.output<typeof IntegrationDiagnosticApi>

export const MarketingDiagnosticResponseApi = zod.object({
    integrations: zod
        .array(
            zod.object({
                integration_key: zod.string().describe("Integration key (e.g. 'google', 'meta')"),
                source_type: zod.string().describe("External data source type key (e.g. 'GoogleAds')"),
                display_name: zod.string().describe('Human-readable integration name'),
                overall_status: zod.string().describe('Per-integration status'),
                diagnosis: zod.string().describe('Human-readable cross-domain diagnosis'),
                data_source: zod
                    .union([
                        zod.object({
                            source_type: zod
                                .string()
                                .describe("External data source type key (e.g. 'GoogleAds', 'MetaAds')"),
                            is_native: zod.boolean().describe('Whether this is a native marketing integration'),
                            display_name: zod.string().describe("Human-readable integration name (e.g. 'Google Ads')"),
                            connected: zod.boolean().describe('Whether a live source of this type is connected'),
                            last_sync_at: zod.iso
                                .datetime({ offset: true })
                                .nullable()
                                .describe('When the source last completed a sync'),
                            last_sync_status: zod
                                .string()
                                .describe('Sync status: ok\/error\/stale\/tables_failed\/not_connected\/never'),
                            last_error: zod
                                .string()
                                .nullable()
                                .describe('Latest unresolved sync error message, if any'),
                            rows_last_24h: zod.number().describe('Rows synced in the last 24 hours'),
                            rows_last_7d: zod.number().describe('Rows synced in the last 7 days'),
                            sources_map_present: zod
                                .boolean()
                                .describe('Whether a column mapping exists for this source'),
                            schema_columns_mapped: zod
                                .array(zod.string())
                                .describe('Schema columns currently mapped for this source'),
                            schema_columns_required_missing: zod
                                .array(zod.string())
                                .describe('Required schema columns that are not yet mapped'),
                            required_tables: zod
                                .array(
                                    zod.object({
                                        table_name: zod
                                            .string()
                                            .describe(
                                                "Name of the required source table (e.g. 'campaign', 'campaign_stats')"
                                            ),
                                        present: zod
                                            .boolean()
                                            .describe('Whether the table exists as a schema on the connected source'),
                                        should_sync: zod.boolean().describe('Whether the table is enabled for sync'),
                                        status: zod
                                            .string()
                                            .nullable()
                                            .describe(
                                                'ExternalDataSchema status: Completed\/Running\/Failed\/Paused\/Cancelled, or null'
                                            ),
                                        last_synced_at: zod.iso
                                            .datetime({ offset: true })
                                            .nullable()
                                            .describe('When this table last completed a sync'),
                                    })
                                )
                                .describe('Per-required-table sync status for this integration'),
                            settings_url: zod.string().describe('URL to the Marketing analytics global settings page'),
                            schemas_url: zod
                                .string()
                                .nullable()
                                .describe('URL to the per-source Schemas tab, or null if not connected'),
                            diagnosis: zod.string().describe("Human-readable diagnosis of this source's health"),
                            fix_suggestion: zod
                                .string()
                                .nullable()
                                .describe('Suggested fix when the source is unhealthy'),
                        }),
                        zod.null(),
                    ])
                    .optional()
                    .describe('Data-source (sync) side health, or null if not connected'),
                attribution: zod
                    .union([
                        zod.object({
                            integration_key: zod.string().describe("Integration key (e.g. 'google', 'meta')"),
                            display_name: zod.string().describe('Human-readable integration name'),
                            events_with_utm_last_7d: zod
                                .number()
                                .describe('Total events with any utm_source in the window'),
                            events_matched_last_7d: zod
                                .number()
                                .describe('Events whose utm_source matched this integration'),
                            events_unmatched_likely_yours_last_7d: zod
                                .number()
                                .describe("Events that look like this integration's but don't match exactly"),
                            last_event_with_matching_utm_at: zod.iso
                                .datetime({ offset: true })
                                .nullable()
                                .describe('Timestamp of the most recent matched event'),
                            matched_pct: zod.number().describe('Percentage of UTM events matched to this integration'),
                            sample_unmatched_utm_sources: zod
                                .array(
                                    zod.object({
                                        raw_value: zod
                                            .string()
                                            .describe(
                                                "A raw utm_source value that doesn't match the integration exactly"
                                            ),
                                        event_count: zod
                                            .number()
                                            .describe('Number of events with this raw value in the window'),
                                        suggested_integration: zod
                                            .string()
                                            .nullable()
                                            .describe('Integration suggested by token match, if any'),
                                    })
                                )
                                .describe('Sample of likely-yours unmatched utm_source values'),
                        }),
                        zod.null(),
                    ])
                    .optional()
                    .describe('Attribution (UTM events) side health, or null if no data'),
                recommended_actions: zod
                    .array(
                        zod.object({
                            title: zod.string().describe('Short title of the recommended action'),
                            detail: zod.string().describe('Detailed explanation of the action'),
                            severity: zod.string().describe('Action severity'),
                            target_tool: zod.string().nullable().describe('Follow-up tool to call next, if any'),
                        })
                    )
                    .describe('Recommended next steps for this integration'),
            })
        )
        .describe('Per-integration cross-domain diagnostics'),
    overall_status: zod.string().describe('healthy\/degraded\/broken\/no_sources'),
    summary: zod.string().describe('One-line plain-English summary of the diagnostic'),
    conversion_goals: zod
        .union([
            zod.object({
                goals: zod
                    .array(
                        zod.object({
                            id: zod.string().describe('Unique id of the goal (event name, action id, or DW goal id)'),
                            name: zod.string().describe('Display name of the conversion goal'),
                            kind: zod
                                .string()
                                .describe(
                                    'Goal type — one of: EventsNode (PostHog event), ActionsNode (PostHog action), DataWarehouseNode (external table)'
                                ),
                            target_label: zod
                                .string()
                                .describe('Human-readable target the goal matches (event\/action name or table)'),
                            last_30d_count: zod
                                .number()
                                .describe('Count of matching conversion events in the last 30 days'),
                            integrated_count: zod
                                .number()
                                .nullable()
                                .describe(
                                    'Conversions whose utm_source matches a known integration. Null for DataWarehouseNode goals.'
                                ),
                            events_without_utm_source: zod
                                .number()
                                .nullable()
                                .describe(
                                    'Conversions with no utm_source at all (fix by tagging UTMs). Null for DataWarehouseNode goals.'
                                ),
                            events_with_unmatched_utm_source: zod
                                .number()
                                .nullable()
                                .describe(
                                    'Conversions with a utm_source that matches no integration (fix with custom_source_mappings). Null for DataWarehouseNode goals.'
                                ),
                            non_integrated_count: zod
                                .number()
                                .nullable()
                                .describe(
                                    'Total non-integrated conversions (without + unmatched utm_source). Null for DataWarehouseNode goals.'
                                ),
                            integrated_pct: zod
                                .number()
                                .nullable()
                                .describe(
                                    'Percentage of conversions that are integrated. Null for DataWarehouseNode goals.'
                                ),
                            is_misconfigured: zod
                                .boolean()
                                .describe('Whether the goal could not be evaluated (e.g. deleted action)'),
                            misconfig_reason: zod
                                .string()
                                .nullable()
                                .describe('Explanation when is_misconfigured is true'),
                            is_approximate: zod
                                .boolean()
                                .describe(
                                    "True when this 30d count may differ from the dashboard's attribution-windowed number"
                                ),
                            approximation_reason: zod
                                .string()
                                .nullable()
                                .describe('Explanation when is_approximate is true'),
                        })
                    )
                    .describe('One summary entry per configured conversion goal'),
                attribution_window_days: zod.number().describe("The team's configured attribution window in days"),
                attribution_mode: zod
                    .string()
                    .describe("The team's attribution model (e.g. last_touch, first_touch, linear)"),
                has_misconfigured: zod.boolean().describe('True if any goal is misconfigured'),
            }),
            zod.null(),
        ])
        .optional()
        .describe('Conversion goal summary, when requested'),
    recommended_actions: zod
        .array(
            zod.object({
                title: zod.string().describe('Short title of the recommended action'),
                detail: zod.string().describe('Detailed explanation of the action'),
                severity: zod.string().describe('Action severity'),
                target_tool: zod.string().nullable().describe('Follow-up tool to call next, if any'),
            })
        )
        .describe('Top global recommended actions across all integrations'),
})

export type MarketingDiagnosticResponseApi = zod.input<typeof MarketingDiagnosticResponseApi>
export type MarketingDiagnosticResponseApiOutput = zod.output<typeof MarketingDiagnosticResponseApi>

export const GoalExplanationPeriodApi = zod.object({
    date_from: zod.string().nullable().describe('Start of the analyzed period (ISO)'),
    date_to: zod.string().nullable().describe('End of the analyzed period (ISO)'),
})

export type GoalExplanationPeriodApi = zod.input<typeof GoalExplanationPeriodApi>
export type GoalExplanationPeriodApiOutput = zod.output<typeof GoalExplanationPeriodApi>

export const GoalEventSampleApi = zod.object({
    event_uuid: zod.string().describe('UUID of the sampled conversion event'),
    timestamp: zod.iso.datetime({ offset: true }).describe('When the event occurred'),
    distinct_id: zod.string().describe('Distinct id associated with the event'),
    utm_source: zod.string().nullable().describe('utm_source value on the event, if any'),
    utm_campaign: zod.string().nullable().describe('utm_campaign value on the event, if any'),
    matched_integration: zod.string().nullable().describe('Integration the utm_source matched, if any'),
})

export type GoalEventSampleApi = zod.input<typeof GoalEventSampleApi>
export type GoalEventSampleApiOutput = zod.output<typeof GoalEventSampleApi>

export const GoalExplanationApi = zod.object({
    goal_id: zod.string().describe('Id of the explained conversion goal'),
    goal_name: zod.string().describe('Display name of the conversion goal'),
    kind: zod.string().describe('EventsNode\/ActionsNode\/DataWarehouseNode'),
    period: zod
        .object({
            date_from: zod.string().nullable().describe('Start of the analyzed period (ISO)'),
            date_to: zod.string().nullable().describe('End of the analyzed period (ISO)'),
        })
        .describe('The period the breakdown was computed over'),
    total_count: zod.number().describe('Total matching conversion events in the period'),
    integrated_count: zod
        .number()
        .nullable()
        .describe('Events whose utm_source matched a known integration. Null for DataWarehouseNode.'),
    events_without_utm_source: zod
        .number()
        .nullable()
        .describe('Events with no utm_source at all. Null for DataWarehouseNode.'),
    events_with_unmatched_utm_source: zod
        .number()
        .nullable()
        .describe('Events with a utm_source matching no integration. Null for DataWarehouseNode.'),
    non_integrated_count: zod
        .number()
        .nullable()
        .describe('Total non-integrated events (without + unmatched). Null for DataWarehouseNode.'),
    by_event: zod.array(zod.tuple([zod.string(), zod.number()])).describe('List of [event_name, count] pairs'),
    by_utm_source: zod.array(zod.tuple([zod.string(), zod.number()])).describe('List of [utm_source, count] pairs'),
    by_matched_integration: zod
        .array(zod.tuple([zod.string(), zod.number()]))
        .describe('List of [integration, count] pairs'),
    samples: zod
        .array(
            zod.object({
                event_uuid: zod.string().describe('UUID of the sampled conversion event'),
                timestamp: zod.iso.datetime({ offset: true }).describe('When the event occurred'),
                distinct_id: zod.string().describe('Distinct id associated with the event'),
                utm_source: zod.string().nullable().describe('utm_source value on the event, if any'),
                utm_campaign: zod.string().nullable().describe('utm_campaign value on the event, if any'),
                matched_integration: zod.string().nullable().describe('Integration the utm_source matched, if any'),
            })
        )
        .describe('A small sample of matching events'),
    notes: zod.array(zod.string()).describe('Caveats about the breakdown (sampling, attribution, etc.)'),
})

export type GoalExplanationApi = zod.input<typeof GoalExplanationApi>
export type GoalExplanationApiOutput = zod.output<typeof GoalExplanationApi>

export const CandidateEventApi = zod.object({
    event_name: zod.string().describe('Name of the candidate event'),
    last_30d_count: zod.number().describe('Count of this event in the last 30 days'),
    distinct_users_30d: zod.number().describe('Distinct users who triggered the event in 30 days'),
    pct_with_utm_source: zod.number().describe('Percentage of events that carry a utm_source'),
    pct_with_utm_campaign: zod.number().describe('Percentage of events that carry a utm_campaign'),
    top_utm_sources: zod.array(zod.tuple([zod.string(), zod.number()])).describe('List of [utm_source, count] pairs'),
    is_already_a_goal: zod.boolean().describe('Whether this event is already configured as a goal'),
    suggestion_score: zod.number().describe('Ranking score (higher is a stronger candidate)'),
    suggestion_reason: zod.string().describe('Human-readable rationale for the suggestion'),
})

export type CandidateEventApi = zod.input<typeof CandidateEventApi>
export type CandidateEventApiOutput = zod.output<typeof CandidateEventApi>

export const EventSuggestionsResponseApi = zod.object({
    candidates: zod
        .array(
            zod.object({
                event_name: zod.string().describe('Name of the candidate event'),
                last_30d_count: zod.number().describe('Count of this event in the last 30 days'),
                distinct_users_30d: zod.number().describe('Distinct users who triggered the event in 30 days'),
                pct_with_utm_source: zod.number().describe('Percentage of events that carry a utm_source'),
                pct_with_utm_campaign: zod.number().describe('Percentage of events that carry a utm_campaign'),
                top_utm_sources: zod
                    .array(zod.tuple([zod.string(), zod.number()]))
                    .describe('List of [utm_source, count] pairs'),
                is_already_a_goal: zod.boolean().describe('Whether this event is already configured as a goal'),
                suggestion_score: zod.number().describe('Ranking score (higher is a stronger candidate)'),
                suggestion_reason: zod.string().describe('Human-readable rationale for the suggestion'),
            })
        )
        .describe('Ranked candidate events for conversion goals'),
    lookback_days: zod.number().describe('Lookback window in days used for the analysis'),
    excluded_events_count: zod.number().describe('Number of system\/autocaptured events excluded'),
})

export type EventSuggestionsResponseApi = zod.input<typeof EventSuggestionsResponseApi>
export type EventSuggestionsResponseApiOutput = zod.output<typeof EventSuggestionsResponseApi>

export const SourceMappingSuggestionApi = zod.object({
    raw_utm_source: zod.string().describe('The raw utm_source value seen on events'),
    suggested_target: zod.string().describe('Integration key it maps to'),
    suggested_target_display_name: zod.string().describe('Human-readable name of the suggested integration'),
    reason: zod.string().describe('Why this mapping is suggested'),
})

export type SourceMappingSuggestionApi = zod.input<typeof SourceMappingSuggestionApi>
export type SourceMappingSuggestionApiOutput = zod.output<typeof SourceMappingSuggestionApi>

export const CampaignMappingSuggestionApi = zod.object({
    integration: zod.string().describe('Integration key the campaign values belong to'),
    integration_display_name: zod.string().describe('Human-readable integration name'),
    suggested_clean_name: zod.string().describe('Proposed canonical campaign name'),
    raw_campaign_values: zod.array(zod.string()).describe('Raw campaign values clustered under this clean name'),
    confidence: zod.number().describe('Confidence score for the clustering (0-1)'),
    method: zod.string().describe('Mapping method'),
    reason: zod.string().describe('Why these campaign values were clustered together'),
})

export type CampaignMappingSuggestionApi = zod.input<typeof CampaignMappingSuggestionApi>
export type CampaignMappingSuggestionApiOutput = zod.output<typeof CampaignMappingSuggestionApi>

export const RawUnmatchedSampleApi = zod.object({
    raw_utm_source: zod.string().describe('A raw utm_source value matching no integration'),
    event_count: zod.number().describe('Number of events with this raw value in the window'),
    suggested_integration: zod.string().nullable().describe('Integration suggested by token match, if any'),
})

export type RawUnmatchedSampleApi = zod.input<typeof RawUnmatchedSampleApi>
export type RawUnmatchedSampleApiOutput = zod.output<typeof RawUnmatchedSampleApi>

export const CatalogueEntryApi = zod.object({
    raw_utm_source: zod.string().describe('A raw utm_source value seen in the window'),
    event_count: zod.number().describe('Number of events with this value'),
    matched_integration: zod.string().nullable().describe('Integration this value exactly matches, if any'),
    matched_integration_display_name: zod
        .string()
        .nullable()
        .describe('Human-readable name of the matched integration, if any'),
    suggested_integration: zod.string().nullable().describe('Integration suggested by token match, if any'),
})

export type CatalogueEntryApi = zod.input<typeof CatalogueEntryApi>
export type CatalogueEntryApiOutput = zod.output<typeof CatalogueEntryApi>

export const CurrentMappingApi = zod.object({
    raw_utm_source: zod.string().describe('A utm_source value already mapped to an integration'),
    target: zod.string().describe('Integration key it maps to'),
    target_display_name: zod.string().describe('Human-readable name of the target integration'),
    source: zod.string().describe('canonical or team_custom'),
})

export type CurrentMappingApi = zod.input<typeof CurrentMappingApi>
export type CurrentMappingApiOutput = zod.output<typeof CurrentMappingApi>

export const UtmMappingSuggestionsResponseApi = zod.object({
    source_suggestions: zod
        .array(
            zod.object({
                raw_utm_source: zod.string().describe('The raw utm_source value seen on events'),
                suggested_target: zod.string().describe('Integration key it maps to'),
                suggested_target_display_name: zod
                    .string()
                    .describe('Human-readable name of the suggested integration'),
                reason: zod.string().describe('Why this mapping is suggested'),
            })
        )
        .describe('Suggested custom_source_mappings entries'),
    campaign_suggestions: zod
        .array(
            zod.object({
                integration: zod.string().describe('Integration key the campaign values belong to'),
                integration_display_name: zod.string().describe('Human-readable integration name'),
                suggested_clean_name: zod.string().describe('Proposed canonical campaign name'),
                raw_campaign_values: zod
                    .array(zod.string())
                    .describe('Raw campaign values clustered under this clean name'),
                confidence: zod.number().describe('Confidence score for the clustering (0-1)'),
                method: zod.string().describe('Mapping method'),
                reason: zod.string().describe('Why these campaign values were clustered together'),
            })
        )
        .describe('Suggested campaign-name clusters (empty in v1)'),
    raw_unmatched_samples: zod
        .array(
            zod.object({
                raw_utm_source: zod.string().describe('A raw utm_source value matching no integration'),
                event_count: zod.number().describe('Number of events with this raw value in the window'),
                suggested_integration: zod.string().nullable().describe('Integration suggested by token match, if any'),
            })
        )
        .describe('All unmatched raw utm_source values worth reviewing'),
    full_utm_source_catalogue: zod
        .array(
            zod.object({
                raw_utm_source: zod.string().describe('A raw utm_source value seen in the window'),
                event_count: zod.number().describe('Number of events with this value'),
                matched_integration: zod.string().nullable().describe('Integration this value exactly matches, if any'),
                matched_integration_display_name: zod
                    .string()
                    .nullable()
                    .describe('Human-readable name of the matched integration, if any'),
                suggested_integration: zod.string().nullable().describe('Integration suggested by token match, if any'),
            })
        )
        .describe('Every utm_source value seen in the window, matched or not'),
    current_mappings: zod
        .array(
            zod.object({
                raw_utm_source: zod.string().describe('A utm_source value already mapped to an integration'),
                target: zod.string().describe('Integration key it maps to'),
                target_display_name: zod.string().describe('Human-readable name of the target integration'),
                source: zod.string().describe('canonical or team_custom'),
            })
        )
        .describe('Mappings already in effect (canonical + team_custom)'),
    total_unmatched_events_in_window: zod.number().describe('Total events with an unmatched utm_source'),
    total_events_with_utm_in_window: zod.number().describe('Total events with any utm_source'),
    lookback_days_used: zod.number().describe('Lookback window in days used for the analysis'),
    notes: zod.array(zod.string()).describe('Caveats and guidance about the suggestions'),
})

export type UtmMappingSuggestionsResponseApi = zod.input<typeof UtmMappingSuggestionsResponseApi>
export type UtmMappingSuggestionsResponseApiOutput = zod.output<typeof UtmMappingSuggestionsResponseApi>

export const UtmIssueSeverityEnumApi = zod
    .enum(['error', 'warning'])
    .describe('\* `error` - error\n\* `warning` - warning')

export type UtmIssueSeverityEnumApi = zod.input<typeof UtmIssueSeverityEnumApi>
export type UtmIssueSeverityEnumApiOutput = zod.output<typeof UtmIssueSeverityEnumApi>

export const UtmIssueApi = zod.object({
    field: zod.string().describe('The UTM field with the issue (e.g. utm_campaign, utm_source)'),
    severity: zod
        .enum(['error', 'warning'])
        .describe('\* `error` - error\n\* `warning` - warning')
        .describe('Issue severity level\n\n\* `error` - error\n\* `warning` - warning'),
    message: zod.string().describe('Human-readable description of the issue'),
})

export type UtmIssueApi = zod.input<typeof UtmIssueApi>
export type UtmIssueApiOutput = zod.output<typeof UtmIssueApi>

export const CampaignAuditResultApi = zod.object({
    campaign_name: zod.string().describe('Campaign name from the ad platform'),
    campaign_id: zod.string().describe('Campaign ID from the ad platform'),
    source_name: zod.string().describe('Integration source name (e.g. google, meta)'),
    spend: zod.number().describe('Total spend for this campaign in the period'),
    clicks: zod.number().describe('Total clicks for this campaign'),
    impressions: zod.number().describe('Total impressions for this campaign'),
    has_utm_events: zod.boolean().describe('Whether matching UTM pageview events were found'),
    event_count: zod.number().describe('Number of matching UTM pageview events'),
    issues: zod
        .array(
            zod.object({
                field: zod.string().describe('The UTM field with the issue (e.g. utm_campaign, utm_source)'),
                severity: zod
                    .enum(['error', 'warning'])
                    .describe('\* `error` - error\n\* `warning` - warning')
                    .describe('Issue severity level\n\n\* `error` - error\n\* `warning` - warning'),
                message: zod.string().describe('Human-readable description of the issue'),
            })
        )
        .describe('List of detected UTM configuration issues'),
})

export type CampaignAuditResultApi = zod.input<typeof CampaignAuditResultApi>
export type CampaignAuditResultApiOutput = zod.output<typeof CampaignAuditResultApi>

export const SourceMatchEnumApi = zod
    .enum(['none', 'auto', 'mapped'])
    .describe('\* `none` - none\n\* `auto` - auto\n\* `mapped` - mapped')

export type SourceMatchEnumApi = zod.input<typeof SourceMatchEnumApi>
export type SourceMatchEnumApiOutput = zod.output<typeof SourceMatchEnumApi>

export const UtmEventApi = zod.object({
    utm_campaign: zod.string().describe('UTM campaign value from pageview events'),
    utm_source: zod.string().describe('UTM source value from pageview events'),
    event_count: zod.number().describe('Number of pageview events with this UTM combination'),
    campaign_match: zod
        .enum(['none', 'auto', 'mapped'])
        .describe('\* `none` - none\n\* `auto` - auto\n\* `mapped` - mapped')
        .describe(
            'How utm_campaign matched: none, auto (direct name\/id), or mapped (manual mapping)\n\n\* `none` - none\n\* `auto` - auto\n\* `mapped` - mapped'
        ),
    source_match: zod
        .enum(['none', 'auto', 'mapped'])
        .describe('\* `none` - none\n\* `auto` - auto\n\* `mapped` - mapped')
        .describe(
            'How utm_source matched: none, auto (default source), or mapped (custom mapping)\n\n\* `none` - none\n\* `auto` - auto\n\* `mapped` - mapped'
        ),
    matched_campaign: zod.string().nullable().describe('Name of the matched campaign, if any'),
})

export type UtmEventApi = zod.input<typeof UtmEventApi>
export type UtmEventApiOutput = zod.output<typeof UtmEventApi>

export const UtmAuditResponseApi = zod.object({
    total_campaigns: zod.number().describe('Total number of campaigns with spend'),
    campaigns_with_issues: zod.number().describe('Number of campaigns with UTM issues'),
    campaigns_without_issues: zod.number().describe('Number of campaigns without issues'),
    total_spend_at_risk: zod.number().describe('Total spend on campaigns with UTM issues'),
    results: zod
        .array(
            zod.object({
                campaign_name: zod.string().describe('Campaign name from the ad platform'),
                campaign_id: zod.string().describe('Campaign ID from the ad platform'),
                source_name: zod.string().describe('Integration source name (e.g. google, meta)'),
                spend: zod.number().describe('Total spend for this campaign in the period'),
                clicks: zod.number().describe('Total clicks for this campaign'),
                impressions: zod.number().describe('Total impressions for this campaign'),
                has_utm_events: zod.boolean().describe('Whether matching UTM pageview events were found'),
                event_count: zod.number().describe('Number of matching UTM pageview events'),
                issues: zod
                    .array(
                        zod.object({
                            field: zod
                                .string()
                                .describe('The UTM field with the issue (e.g. utm_campaign, utm_source)'),
                            severity: zod
                                .enum(['error', 'warning'])
                                .describe('\* `error` - error\n\* `warning` - warning')
                                .describe('Issue severity level\n\n\* `error` - error\n\* `warning` - warning'),
                            message: zod.string().describe('Human-readable description of the issue'),
                        })
                    )
                    .describe('List of detected UTM configuration issues'),
            })
        )
        .describe('Audit results per campaign'),
    all_utm_events: zod
        .array(
            zod.object({
                utm_campaign: zod.string().describe('UTM campaign value from pageview events'),
                utm_source: zod.string().describe('UTM source value from pageview events'),
                event_count: zod.number().describe('Number of pageview events with this UTM combination'),
                campaign_match: zod
                    .enum(['none', 'auto', 'mapped'])
                    .describe('\* `none` - none\n\* `auto` - auto\n\* `mapped` - mapped')
                    .describe(
                        'How utm_campaign matched: none, auto (direct name\/id), or mapped (manual mapping)\n\n\* `none` - none\n\* `auto` - auto\n\* `mapped` - mapped'
                    ),
                source_match: zod
                    .enum(['none', 'auto', 'mapped'])
                    .describe('\* `none` - none\n\* `auto` - auto\n\* `mapped` - mapped')
                    .describe(
                        'How utm_source matched: none, auto (default source), or mapped (custom mapping)\n\n\* `none` - none\n\* `auto` - auto\n\* `mapped` - mapped'
                    ),
                matched_campaign: zod.string().nullable().describe('Name of the matched campaign, if any'),
            })
        )
        .describe('All UTM events with match status'),
})

export type UtmAuditResponseApi = zod.input<typeof UtmAuditResponseApi>
export type UtmAuditResponseApiOutput = zod.output<typeof UtmAuditResponseApi>
