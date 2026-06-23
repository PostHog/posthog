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

export const TierEnumApi = zod
    .enum(['high', 'medium', 'low'])
    .describe('\* `high` - high\n\* `medium` - medium\n\* `low` - low')

export type TierEnumApi = zod.input<typeof TierEnumApi>
export type TierEnumApiOutput = zod.output<typeof TierEnumApi>

export const IdentityMatchingLinkApi = zod.object({
    job_id: zod.uuid().describe('Identity matching run that produced this link.'),
    model_version: zod.string().describe("Scoring model that produced the link, e.g. 'rules_v1' or 'logreg_v1'."),
    orphan_distinct_id: zod.string().describe('Anonymous distinct ID that the model linked to an identified person.'),
    anchor_person_key: zod.string().describe('Canonical distinct ID representing the matched identified person.'),
    score: zod.number().describe("Link score: weighted rule points for 'rules_v1', a 0-1 probability for 'logreg_v1'."),
    margin: zod.number().describe('Score margin over the runner-up candidate person for this orphan.'),
    tier: zod
        .enum(['high', 'medium', 'low'])
        .describe('\* `high` - high\n\* `medium` - medium\n\* `low` - low')
        .describe(
            'Confidence tier derived from score thresholds.\n\n\* `high` - high\n\* `medium` - medium\n\* `low` - low'
        ),
    computed_at: zod.iso.datetime({ offset: true }).describe('When the link was computed (UTC).'),
    shared_ip_days: zod.number().describe('Distinct (IP, day) combinations both sides were seen on.'),
    shared_ips: zod.number().describe('Distinct IPs both sides were seen on.'),
    min_ip_block_size: zod
        .number()
        .describe('Device count on the least crowded shared IP-day; small values suggest a household IP.'),
    geo_city_match: zod.boolean().describe('Both sides were seen in the same city.'),
    timezone_match: zod.boolean().describe('Both sides reported the same timezone.'),
    language_match: zod.boolean().describe('Both sides reported the same browser language.'),
    ua_exact_match: zod.boolean().describe('A byte-identical user agent was seen on both sides.'),
    orphan_is_webview: zod.boolean().describe("The orphan's traffic came from an in-app browser or webview."),
    device_type_complement: zod.boolean().describe('The sides form a mobile + desktop device pair.'),
    days_overlap: zod.number().describe('Number of days on which the two sides shared an IP.'),
    avg_path_jaccard: zod
        .number()
        .describe('Average overlap (0-1) of pages visited by the two sides on shared IP-days.'),
    orphan_paid_touch: zod
        .boolean()
        .describe('The orphan arrived via a paid click ID (gclid, li_fat_id, ...) inside the window.'),
    anchor_paid_touch: zod.boolean().describe('The matched person already had a paid click ID inside the window.'),
})

export type IdentityMatchingLinkApi = zod.input<typeof IdentityMatchingLinkApi>
export type IdentityMatchingLinkApiOutput = zod.output<typeof IdentityMatchingLinkApi>

export const IdentityMatchingLinksResponseApi = zod.object({
    results: zod
        .array(
            zod.object({
                job_id: zod.uuid().describe('Identity matching run that produced this link.'),
                model_version: zod
                    .string()
                    .describe("Scoring model that produced the link, e.g. 'rules_v1' or 'logreg_v1'."),
                orphan_distinct_id: zod
                    .string()
                    .describe('Anonymous distinct ID that the model linked to an identified person.'),
                anchor_person_key: zod
                    .string()
                    .describe('Canonical distinct ID representing the matched identified person.'),
                score: zod
                    .number()
                    .describe("Link score: weighted rule points for 'rules_v1', a 0-1 probability for 'logreg_v1'."),
                margin: zod.number().describe('Score margin over the runner-up candidate person for this orphan.'),
                tier: zod
                    .enum(['high', 'medium', 'low'])
                    .describe('\* `high` - high\n\* `medium` - medium\n\* `low` - low')
                    .describe(
                        'Confidence tier derived from score thresholds.\n\n\* `high` - high\n\* `medium` - medium\n\* `low` - low'
                    ),
                computed_at: zod.iso.datetime({ offset: true }).describe('When the link was computed (UTC).'),
                shared_ip_days: zod.number().describe('Distinct (IP, day) combinations both sides were seen on.'),
                shared_ips: zod.number().describe('Distinct IPs both sides were seen on.'),
                min_ip_block_size: zod
                    .number()
                    .describe('Device count on the least crowded shared IP-day; small values suggest a household IP.'),
                geo_city_match: zod.boolean().describe('Both sides were seen in the same city.'),
                timezone_match: zod.boolean().describe('Both sides reported the same timezone.'),
                language_match: zod.boolean().describe('Both sides reported the same browser language.'),
                ua_exact_match: zod.boolean().describe('A byte-identical user agent was seen on both sides.'),
                orphan_is_webview: zod
                    .boolean()
                    .describe("The orphan's traffic came from an in-app browser or webview."),
                device_type_complement: zod.boolean().describe('The sides form a mobile + desktop device pair.'),
                days_overlap: zod.number().describe('Number of days on which the two sides shared an IP.'),
                avg_path_jaccard: zod
                    .number()
                    .describe('Average overlap (0-1) of pages visited by the two sides on shared IP-days.'),
                orphan_paid_touch: zod
                    .boolean()
                    .describe('The orphan arrived via a paid click ID (gclid, li_fat_id, ...) inside the window.'),
                anchor_paid_touch: zod
                    .boolean()
                    .describe('The matched person already had a paid click ID inside the window.'),
            })
        )
        .describe('Links ordered by score, descending.'),
    count: zod.number().describe('Total links matching the filters, ignoring pagination.'),
})

export type IdentityMatchingLinksResponseApi = zod.input<typeof IdentityMatchingLinksResponseApi>
export type IdentityMatchingLinksResponseApiOutput = zod.output<typeof IdentityMatchingLinksResponseApi>

export const IdentityMatchingErrorApi = zod.object({
    detail: zod.string().describe('Human-readable explanation of why the request could not be served.'),
})

export type IdentityMatchingErrorApi = zod.input<typeof IdentityMatchingErrorApi>
export type IdentityMatchingErrorApiOutput = zod.output<typeof IdentityMatchingErrorApi>

export const IdentityMatchingRunModelCountApi = zod.object({
    model_version: zod.string().describe("Scoring model, e.g. 'rules_v1' or 'logreg_v1'."),
    link_count: zod.number().describe('Number of links this model produced in the run.'),
})

export type IdentityMatchingRunModelCountApi = zod.input<typeof IdentityMatchingRunModelCountApi>
export type IdentityMatchingRunModelCountApiOutput = zod.output<typeof IdentityMatchingRunModelCountApi>

export const IdentityMatchingRunApi = zod.object({
    job_id: zod.uuid().describe('Identity matching run identifier (the Dagster run ID).'),
    computed_at: zod.iso.datetime({ offset: true }).describe('When the run wrote its links (UTC).'),
    models: zod
        .array(
            zod.object({
                model_version: zod.string().describe("Scoring model, e.g. 'rules_v1' or 'logreg_v1'."),
                link_count: zod.number().describe('Number of links this model produced in the run.'),
            })
        )
        .describe('Link counts per scoring model in this run.'),
})

export type IdentityMatchingRunApi = zod.input<typeof IdentityMatchingRunApi>
export type IdentityMatchingRunApiOutput = zod.output<typeof IdentityMatchingRunApi>

export const IdentityMatchingRunsResponseApi = zod.object({
    results: zod
        .array(
            zod.object({
                job_id: zod.uuid().describe('Identity matching run identifier (the Dagster run ID).'),
                computed_at: zod.iso.datetime({ offset: true }).describe('When the run wrote its links (UTC).'),
                models: zod
                    .array(
                        zod.object({
                            model_version: zod.string().describe("Scoring model, e.g. 'rules_v1' or 'logreg_v1'."),
                            link_count: zod.number().describe('Number of links this model produced in the run.'),
                        })
                    )
                    .describe('Link counts per scoring model in this run.'),
            })
        )
        .describe('Runs ordered by recency, most recent first.'),
})

export type IdentityMatchingRunsResponseApi = zod.input<typeof IdentityMatchingRunsResponseApi>
export type IdentityMatchingRunsResponseApiOutput = zod.output<typeof IdentityMatchingRunsResponseApi>
