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
