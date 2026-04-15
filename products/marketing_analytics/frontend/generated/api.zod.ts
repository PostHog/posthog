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
 * Cross-reference campaigns with spend from ad platforms against pageview events with UTM parameters to identify tracking issues.
 * @summary Run UTM audit
 */
export const MarketingAnalyticsUtmAuditRetrieveResponse = /* @__PURE__ */ zod.object({
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
                                .describe('* `error` - error\n* `warning` - warning')
                                .describe('Issue severity level\n\n* `error` - error\n* `warning` - warning'),
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
                    .describe('* `none` - none\n* `auto` - auto\n* `mapped` - mapped')
                    .describe(
                        'How utm_campaign matched: none, auto (direct name/id), or mapped (manual mapping)\n\n* `none` - none\n* `auto` - auto\n* `mapped` - mapped'
                    ),
                source_match: zod
                    .enum(['none', 'auto', 'mapped'])
                    .describe('* `none` - none\n* `auto` - auto\n* `mapped` - mapped')
                    .describe(
                        'How utm_source matched: none, auto (default source), or mapped (custom mapping)\n\n* `none` - none\n* `auto` - auto\n* `mapped` - mapped'
                    ),
                matched_campaign: zod.string().nullable().describe('Name of the matched campaign, if any'),
            })
        )
        .describe('All UTM events with match status'),
})
