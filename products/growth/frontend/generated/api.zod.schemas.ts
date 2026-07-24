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

export const ProductPushCampaignApi = zod.object({
    id: zod.uuid().describe("Campaign id. Stable for the campaign's lifetime — key per-user dismissal state on it."),
    product_key: zod.string().describe("ProductKey value of the product being pushed (e.g. 'session_replay')."),
    product_path: zod
        .string()
        .nullable()
        .describe(
            'Sidebar path of the pushed product in the product catalog, for display resolution. Null when the key maps to no released catalog item.'
        ),
    reason_text: zod
        .string()
        .nullable()
        .describe('Custom promo copy written by the TAM. Null means the client should use its default copy.'),
    started_at: zod.iso.datetime({ offset: true }).describe('When this campaign started.'),
    ends_at: zod.iso.datetime({ offset: true }).nullable().describe('When this campaign is planned to end.'),
})

export type ProductPushCampaignApi = zod.input<typeof ProductPushCampaignApi>
export type ProductPushCampaignApiOutput = zod.output<typeof ProductPushCampaignApi>

export const TierEnumApi = zod
    .enum(['high', 'medium', 'low'])
    .describe('\* `high` - high\n\* `medium` - medium\n\* `low` - low')

export type TierEnumApi = zod.input<typeof TierEnumApi>
export type TierEnumApiOutput = zod.output<typeof TierEnumApi>

export const IdentityMatchingPersonApi = zod
    .object({
        distinct_id: zod.string().describe('Distinct ID this person was resolved from.'),
        first_seen: zod.iso
            .datetime({ offset: true })
            .nullable()
            .describe('When this person was first seen — person created_at (UTC).'),
        last_seen: zod.iso
            .datetime({ offset: true })
            .nullable()
            .describe('When this person was last seen, when tracked — person last_seen_at (UTC).'),
        email: zod.string().nullable().describe("Person's email, when set."),
        name: zod.string().nullable().describe("Person's name property, when set."),
        city: zod.string().nullable().describe('GeoIP city ($geoip_city_name).'),
        country: zod.string().nullable().describe('GeoIP country code ($geoip_country_code).'),
        browser: zod.string().nullable().describe('Browser ($browser).'),
        os: zod.string().nullable().describe('Operating system ($os).'),
        device_type: zod.string().nullable().describe('Device type, e.g. Desktop or Mobile ($device_type).'),
        timezone: zod.string().nullable().describe('Browser timezone ($timezone).'),
        utm_source: zod.string().nullable().describe('Initial campaign source ($initial_utm_source).'),
        utm_medium: zod.string().nullable().describe('Initial campaign medium ($initial_utm_medium).'),
        utm_campaign: zod.string().nullable().describe('Initial campaign name ($initial_utm_campaign).'),
        referring_domain: zod.string().nullable().describe('Initial referring domain ($initial_referring_domain).'),
        gclid: zod
            .string()
            .nullable()
            .describe(
                'Initial Google click ID ($initial_gclid); present when the person arrived via a paid Google ad.'
            ),
    })
    .describe(
        'The resolved person behind one side of a link, with a curated set of properties that mirror\nthe match signals (geo, device, campaign) so a reviewer can judge whether the link is plausible.'
    )

export type IdentityMatchingPersonApi = zod.input<typeof IdentityMatchingPersonApi>
export type IdentityMatchingPersonApiOutput = zod.output<typeof IdentityMatchingPersonApi>

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
    orphan_person: zod
        .union([
            zod
                .object({
                    distinct_id: zod.string().describe('Distinct ID this person was resolved from.'),
                    first_seen: zod.iso
                        .datetime({ offset: true })
                        .nullable()
                        .describe('When this person was first seen — person created_at (UTC).'),
                    last_seen: zod.iso
                        .datetime({ offset: true })
                        .nullable()
                        .describe('When this person was last seen, when tracked — person last_seen_at (UTC).'),
                    email: zod.string().nullable().describe("Person's email, when set."),
                    name: zod.string().nullable().describe("Person's name property, when set."),
                    city: zod.string().nullable().describe('GeoIP city ($geoip_city_name).'),
                    country: zod.string().nullable().describe('GeoIP country code ($geoip_country_code).'),
                    browser: zod.string().nullable().describe('Browser ($browser).'),
                    os: zod.string().nullable().describe('Operating system ($os).'),
                    device_type: zod
                        .string()
                        .nullable()
                        .describe('Device type, e.g. Desktop or Mobile ($device_type).'),
                    timezone: zod.string().nullable().describe('Browser timezone ($timezone).'),
                    utm_source: zod.string().nullable().describe('Initial campaign source ($initial_utm_source).'),
                    utm_medium: zod.string().nullable().describe('Initial campaign medium ($initial_utm_medium).'),
                    utm_campaign: zod.string().nullable().describe('Initial campaign name ($initial_utm_campaign).'),
                    referring_domain: zod
                        .string()
                        .nullable()
                        .describe('Initial referring domain ($initial_referring_domain).'),
                    gclid: zod
                        .string()
                        .nullable()
                        .describe(
                            'Initial Google click ID ($initial_gclid); present when the person arrived via a paid Google ad.'
                        ),
                })
                .describe(
                    'The resolved person behind one side of a link, with a curated set of properties that mirror\nthe match signals (geo, device, campaign) so a reviewer can judge whether the link is plausible.'
                ),
            zod.null(),
        ])
        .describe('Resolved person behind the anonymous distinct ID; null when no profile exists for it.'),
    anchor_person: zod
        .union([
            zod
                .object({
                    distinct_id: zod.string().describe('Distinct ID this person was resolved from.'),
                    first_seen: zod.iso
                        .datetime({ offset: true })
                        .nullable()
                        .describe('When this person was first seen — person created_at (UTC).'),
                    last_seen: zod.iso
                        .datetime({ offset: true })
                        .nullable()
                        .describe('When this person was last seen, when tracked — person last_seen_at (UTC).'),
                    email: zod.string().nullable().describe("Person's email, when set."),
                    name: zod.string().nullable().describe("Person's name property, when set."),
                    city: zod.string().nullable().describe('GeoIP city ($geoip_city_name).'),
                    country: zod.string().nullable().describe('GeoIP country code ($geoip_country_code).'),
                    browser: zod.string().nullable().describe('Browser ($browser).'),
                    os: zod.string().nullable().describe('Operating system ($os).'),
                    device_type: zod
                        .string()
                        .nullable()
                        .describe('Device type, e.g. Desktop or Mobile ($device_type).'),
                    timezone: zod.string().nullable().describe('Browser timezone ($timezone).'),
                    utm_source: zod.string().nullable().describe('Initial campaign source ($initial_utm_source).'),
                    utm_medium: zod.string().nullable().describe('Initial campaign medium ($initial_utm_medium).'),
                    utm_campaign: zod.string().nullable().describe('Initial campaign name ($initial_utm_campaign).'),
                    referring_domain: zod
                        .string()
                        .nullable()
                        .describe('Initial referring domain ($initial_referring_domain).'),
                    gclid: zod
                        .string()
                        .nullable()
                        .describe(
                            'Initial Google click ID ($initial_gclid); present when the person arrived via a paid Google ad.'
                        ),
                })
                .describe(
                    'The resolved person behind one side of a link, with a curated set of properties that mirror\nthe match signals (geo, device, campaign) so a reviewer can judge whether the link is plausible.'
                ),
            zod.null(),
        ])
        .describe('Resolved identified person behind the matched person key; null when no profile exists for it.'),
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
                orphan_person: zod
                    .union([
                        zod
                            .object({
                                distinct_id: zod.string().describe('Distinct ID this person was resolved from.'),
                                first_seen: zod.iso
                                    .datetime({ offset: true })
                                    .nullable()
                                    .describe('When this person was first seen — person created_at (UTC).'),
                                last_seen: zod.iso
                                    .datetime({ offset: true })
                                    .nullable()
                                    .describe(
                                        'When this person was last seen, when tracked — person last_seen_at (UTC).'
                                    ),
                                email: zod.string().nullable().describe("Person's email, when set."),
                                name: zod.string().nullable().describe("Person's name property, when set."),
                                city: zod.string().nullable().describe('GeoIP city ($geoip_city_name).'),
                                country: zod.string().nullable().describe('GeoIP country code ($geoip_country_code).'),
                                browser: zod.string().nullable().describe('Browser ($browser).'),
                                os: zod.string().nullable().describe('Operating system ($os).'),
                                device_type: zod
                                    .string()
                                    .nullable()
                                    .describe('Device type, e.g. Desktop or Mobile ($device_type).'),
                                timezone: zod.string().nullable().describe('Browser timezone ($timezone).'),
                                utm_source: zod
                                    .string()
                                    .nullable()
                                    .describe('Initial campaign source ($initial_utm_source).'),
                                utm_medium: zod
                                    .string()
                                    .nullable()
                                    .describe('Initial campaign medium ($initial_utm_medium).'),
                                utm_campaign: zod
                                    .string()
                                    .nullable()
                                    .describe('Initial campaign name ($initial_utm_campaign).'),
                                referring_domain: zod
                                    .string()
                                    .nullable()
                                    .describe('Initial referring domain ($initial_referring_domain).'),
                                gclid: zod
                                    .string()
                                    .nullable()
                                    .describe(
                                        'Initial Google click ID ($initial_gclid); present when the person arrived via a paid Google ad.'
                                    ),
                            })
                            .describe(
                                'The resolved person behind one side of a link, with a curated set of properties that mirror\nthe match signals (geo, device, campaign) so a reviewer can judge whether the link is plausible.'
                            ),
                        zod.null(),
                    ])
                    .describe('Resolved person behind the anonymous distinct ID; null when no profile exists for it.'),
                anchor_person: zod
                    .union([
                        zod
                            .object({
                                distinct_id: zod.string().describe('Distinct ID this person was resolved from.'),
                                first_seen: zod.iso
                                    .datetime({ offset: true })
                                    .nullable()
                                    .describe('When this person was first seen — person created_at (UTC).'),
                                last_seen: zod.iso
                                    .datetime({ offset: true })
                                    .nullable()
                                    .describe(
                                        'When this person was last seen, when tracked — person last_seen_at (UTC).'
                                    ),
                                email: zod.string().nullable().describe("Person's email, when set."),
                                name: zod.string().nullable().describe("Person's name property, when set."),
                                city: zod.string().nullable().describe('GeoIP city ($geoip_city_name).'),
                                country: zod.string().nullable().describe('GeoIP country code ($geoip_country_code).'),
                                browser: zod.string().nullable().describe('Browser ($browser).'),
                                os: zod.string().nullable().describe('Operating system ($os).'),
                                device_type: zod
                                    .string()
                                    .nullable()
                                    .describe('Device type, e.g. Desktop or Mobile ($device_type).'),
                                timezone: zod.string().nullable().describe('Browser timezone ($timezone).'),
                                utm_source: zod
                                    .string()
                                    .nullable()
                                    .describe('Initial campaign source ($initial_utm_source).'),
                                utm_medium: zod
                                    .string()
                                    .nullable()
                                    .describe('Initial campaign medium ($initial_utm_medium).'),
                                utm_campaign: zod
                                    .string()
                                    .nullable()
                                    .describe('Initial campaign name ($initial_utm_campaign).'),
                                referring_domain: zod
                                    .string()
                                    .nullable()
                                    .describe('Initial referring domain ($initial_referring_domain).'),
                                gclid: zod
                                    .string()
                                    .nullable()
                                    .describe(
                                        'Initial Google click ID ($initial_gclid); present when the person arrived via a paid Google ad.'
                                    ),
                            })
                            .describe(
                                'The resolved person behind one side of a link, with a curated set of properties that mirror\nthe match signals (geo, device, campaign) so a reviewer can judge whether the link is plausible.'
                            ),
                        zod.null(),
                    ])
                    .describe(
                        'Resolved identified person behind the matched person key; null when no profile exists for it.'
                    ),
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
    high_confidence: zod.number().describe("Links from this model in the 'high' tier."),
    medium_confidence: zod.number().describe("Links from this model in the 'medium' tier."),
    low_confidence: zod.number().describe("Links from this model in the 'low' tier."),
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
                high_confidence: zod.number().describe("Links from this model in the 'high' tier."),
                medium_confidence: zod.number().describe("Links from this model in the 'medium' tier."),
                low_confidence: zod.number().describe("Links from this model in the 'low' tier."),
            })
        )
        .describe('Link counts per scoring model in this run.'),
    total_links: zod.number().describe('Total links across all models in this run.'),
    unique_orphans: zod.number().describe('Distinct anonymous visitors that were linked.'),
    paid_touches: zod.number().describe('Links where a paid ad click was recovered for an anonymous visitor.'),
    first_link_at: zod.iso.datetime({ offset: true }).describe('Earliest link computed_at in the run (UTC).'),
    last_link_at: zod.iso.datetime({ offset: true }).describe('Latest link computed_at in the run (UTC).'),
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
                            high_confidence: zod.number().describe("Links from this model in the 'high' tier."),
                            medium_confidence: zod.number().describe("Links from this model in the 'medium' tier."),
                            low_confidence: zod.number().describe("Links from this model in the 'low' tier."),
                        })
                    )
                    .describe('Link counts per scoring model in this run.'),
                total_links: zod.number().describe('Total links across all models in this run.'),
                unique_orphans: zod.number().describe('Distinct anonymous visitors that were linked.'),
                paid_touches: zod
                    .number()
                    .describe('Links where a paid ad click was recovered for an anonymous visitor.'),
                first_link_at: zod.iso
                    .datetime({ offset: true })
                    .describe('Earliest link computed_at in the run (UTC).'),
                last_link_at: zod.iso.datetime({ offset: true }).describe('Latest link computed_at in the run (UTC).'),
            })
        )
        .describe('Runs ordered by recency, most recent first.'),
})

export type IdentityMatchingRunsResponseApi = zod.input<typeof IdentityMatchingRunsResponseApi>
export type IdentityMatchingRunsResponseApiOutput = zod.output<typeof IdentityMatchingRunsResponseApi>

export const OverallHealthEnumApi = zod
    .enum(['healthy', 'needs_attention'])
    .describe('\* `healthy` - healthy\n\* `needs_attention` - needs_attention')

export type OverallHealthEnumApi = zod.input<typeof OverallHealthEnumApi>
export type OverallHealthEnumApiOutput = zod.output<typeof OverallHealthEnumApi>

export const HealthEnumApi = zod
    .enum(['success', 'warning', 'danger'])
    .describe('\* `success` - success\n\* `warning` - warning\n\* `danger` - danger')

export type HealthEnumApi = zod.input<typeof HealthEnumApi>
export type HealthEnumApiOutput = zod.output<typeof HealthEnumApi>

export const LibEnumApi = zod
    .enum([
        'web',
        'posthog-ios',
        'posthog-android',
        'posthog-java',
        'posthog-server',
        'posthog-node',
        'posthog-python',
        'posthog-php',
        'posthog-ruby',
        'posthog-go',
        'posthog-flutter',
        'posthog-react-native',
        'posthog-kmp',
        'posthog-dotnet',
        'posthog-elixir',
    ])
    .describe(
        '\* `web` - web\n\* `posthog-ios` - posthog-ios\n\* `posthog-android` - posthog-android\n\* `posthog-java` - posthog-java\n\* `posthog-server` - posthog-server\n\* `posthog-node` - posthog-node\n\* `posthog-python` - posthog-python\n\* `posthog-php` - posthog-php\n\* `posthog-ruby` - posthog-ruby\n\* `posthog-go` - posthog-go\n\* `posthog-flutter` - posthog-flutter\n\* `posthog-react-native` - posthog-react-native\n\* `posthog-kmp` - posthog-kmp\n\* `posthog-dotnet` - posthog-dotnet\n\* `posthog-elixir` - posthog-elixir'
    )

export type LibEnumApi = zod.input<typeof LibEnumApi>
export type LibEnumApiOutput = zod.output<typeof LibEnumApi>

export const SdkAssessmentSeverityEnumApi = zod
    .enum(['none', 'warning', 'danger'])
    .describe('\* `none` - none\n\* `warning` - warning\n\* `danger` - danger')

export type SdkAssessmentSeverityEnumApi = zod.input<typeof SdkAssessmentSeverityEnumApi>
export type SdkAssessmentSeverityEnumApiOutput = zod.output<typeof SdkAssessmentSeverityEnumApi>

export const SdkReleaseAssessmentApi = zod.object({
    version: zod.string().describe("In-use SDK version string, e.g. '1.298.0'."),
    count: zod.number().describe('Number of events captured with this version in the last 7 days.'),
    max_timestamp: zod.string().describe('Timestamp of the most recent event seen for this version (ISO 8601).'),
    release_date: zod
        .string()
        .nullable()
        .describe('When this version was published on GitHub (ISO 8601), or null if unknown.'),
    days_since_release: zod.number().nullable().describe('Days since this version was released, or null if unknown.'),
    released_ago: zod
        .string()
        .nullable()
        .describe(
            "Human-readable relative release age matching the UI (e.g. '5 months ago'). Null when release_date is unknown."
        ),
    is_outdated: zod.boolean().describe('True when this version is flagged as outdated by smart-semver rules.'),
    is_old: zod
        .boolean()
        .describe('True when this version is flagged as old by age alone (separate from semver rules).'),
    needs_updating: zod.boolean().describe('True if is_outdated OR is_old.'),
    is_current_or_newer: zod
        .boolean()
        .describe('True when this version equals or exceeds the latest known published version.'),
    status_reason: zod
        .string()
        .describe(
            "Per-version badge tooltip text matching the SDK Health UI exactly. Quote verbatim when reporting to users. Varies by state: 'Released X ago. Upgrade recommended.' for outdated versions, 'You have the latest available.' for current versions, or 'Released X ago. Upgrading is a good idea, but it's not urgent yet.' for recent-but-behind versions."
        ),
    sql_query: zod
        .string()
        .describe(
            'SQL SELECT statement for drilling into events for this SDK version over the last 7 days. Suitable to pass to the execute-sql tool or to display as a copy-paste snippet.'
        ),
    activity_page_url: zod
        .string()
        .describe(
            "Relative URL path (starting with \/project\/{id}\/) for the Activity > Explore page pre-filtered to events captured with this lib and lib_version over the last 7 days. Combine with the user's PostHog host (e.g. us.posthog.com) for a clickable link."
        ),
})

export type SdkReleaseAssessmentApi = zod.input<typeof SdkReleaseAssessmentApi>
export type SdkReleaseAssessmentApiOutput = zod.output<typeof SdkReleaseAssessmentApi>

export const OutdatedTrafficAlertApi = zod.object({
    version: zod.string().describe('Outdated version handling significant traffic.'),
    threshold_percent: zod
        .number()
        .describe('Traffic-percentage threshold that triggered the alert (10% for most SDKs, 20% for web).'),
})

export type OutdatedTrafficAlertApi = zod.input<typeof OutdatedTrafficAlertApi>
export type OutdatedTrafficAlertApiOutput = zod.output<typeof OutdatedTrafficAlertApi>

export const SdkAssessmentApi = zod.object({
    lib: zod
        .enum([
            'web',
            'posthog-ios',
            'posthog-android',
            'posthog-java',
            'posthog-server',
            'posthog-node',
            'posthog-python',
            'posthog-php',
            'posthog-ruby',
            'posthog-go',
            'posthog-flutter',
            'posthog-react-native',
            'posthog-kmp',
            'posthog-dotnet',
            'posthog-elixir',
        ])
        .describe(
            '\* `web` - web\n\* `posthog-ios` - posthog-ios\n\* `posthog-android` - posthog-android\n\* `posthog-java` - posthog-java\n\* `posthog-server` - posthog-server\n\* `posthog-node` - posthog-node\n\* `posthog-python` - posthog-python\n\* `posthog-php` - posthog-php\n\* `posthog-ruby` - posthog-ruby\n\* `posthog-go` - posthog-go\n\* `posthog-flutter` - posthog-flutter\n\* `posthog-react-native` - posthog-react-native\n\* `posthog-kmp` - posthog-kmp\n\* `posthog-dotnet` - posthog-dotnet\n\* `posthog-elixir` - posthog-elixir'
        )
        .describe(
            "SDK identifier, e.g. 'web', 'posthog-python', 'posthog-node', 'posthog-ios'.\n\n\* `web` - web\n\* `posthog-ios` - posthog-ios\n\* `posthog-android` - posthog-android\n\* `posthog-java` - posthog-java\n\* `posthog-server` - posthog-server\n\* `posthog-node` - posthog-node\n\* `posthog-python` - posthog-python\n\* `posthog-php` - posthog-php\n\* `posthog-ruby` - posthog-ruby\n\* `posthog-go` - posthog-go\n\* `posthog-flutter` - posthog-flutter\n\* `posthog-react-native` - posthog-react-native\n\* `posthog-kmp` - posthog-kmp\n\* `posthog-dotnet` - posthog-dotnet\n\* `posthog-elixir` - posthog-elixir"
        ),
    readable_name: zod
        .string()
        .describe("Human-readable SDK name matching the SDK Health UI (e.g. 'Python', 'Node.js', 'Web', 'iOS')."),
    latest_version: zod.string().describe('Most recent published version of this SDK.'),
    needs_updating: zod.boolean().describe('True if this SDK needs attention (is_outdated OR is_old).'),
    is_outdated: zod.boolean().describe('True if the primary in-use version is flagged as outdated.'),
    is_old: zod.boolean().describe('True if the primary in-use version is flagged as old by age alone.'),
    migration_required: zod
        .boolean()
        .describe('True when this SDK must be replaced by a supported successor rather than upgraded in place.'),
    severity: zod
        .enum(['none', 'warning', 'danger'])
        .describe('\* `none` - none\n\* `warning` - warning\n\* `danger` - danger')
        .describe(
            "UI severity badge — 'none' when healthy, 'warning' when outdated, 'danger' when the majority of team SDKs are outdated.\n\n\* `none` - none\n\* `warning` - warning\n\* `danger` - danger"
        ),
    reason: zod
        .string()
        .describe(
            'Per-SDK programmatic summary (used for ranking\/filtering). For user-facing copy, prefer releases[].status_reason (badge tooltip) and banners (top-level alert text) — those match the UI exactly.'
        ),
    banners: zod
        .array(zod.string())
        .describe(
            "Top-level alert sentences matching the SDK Health UI's 'Time for an update!' banner — one per outdated version with significant traffic. Quote verbatim when surfacing the headline to users."
        ),
    releases: zod
        .array(
            zod.object({
                version: zod.string().describe("In-use SDK version string, e.g. '1.298.0'."),
                count: zod.number().describe('Number of events captured with this version in the last 7 days.'),
                max_timestamp: zod
                    .string()
                    .describe('Timestamp of the most recent event seen for this version (ISO 8601).'),
                release_date: zod
                    .string()
                    .nullable()
                    .describe('When this version was published on GitHub (ISO 8601), or null if unknown.'),
                days_since_release: zod
                    .number()
                    .nullable()
                    .describe('Days since this version was released, or null if unknown.'),
                released_ago: zod
                    .string()
                    .nullable()
                    .describe(
                        "Human-readable relative release age matching the UI (e.g. '5 months ago'). Null when release_date is unknown."
                    ),
                is_outdated: zod
                    .boolean()
                    .describe('True when this version is flagged as outdated by smart-semver rules.'),
                is_old: zod
                    .boolean()
                    .describe('True when this version is flagged as old by age alone (separate from semver rules).'),
                needs_updating: zod.boolean().describe('True if is_outdated OR is_old.'),
                is_current_or_newer: zod
                    .boolean()
                    .describe('True when this version equals or exceeds the latest known published version.'),
                status_reason: zod
                    .string()
                    .describe(
                        "Per-version badge tooltip text matching the SDK Health UI exactly. Quote verbatim when reporting to users. Varies by state: 'Released X ago. Upgrade recommended.' for outdated versions, 'You have the latest available.' for current versions, or 'Released X ago. Upgrading is a good idea, but it's not urgent yet.' for recent-but-behind versions."
                    ),
                sql_query: zod
                    .string()
                    .describe(
                        'SQL SELECT statement for drilling into events for this SDK version over the last 7 days. Suitable to pass to the execute-sql tool or to display as a copy-paste snippet.'
                    ),
                activity_page_url: zod
                    .string()
                    .describe(
                        "Relative URL path (starting with \/project\/{id}\/) for the Activity > Explore page pre-filtered to events captured with this lib and lib_version over the last 7 days. Combine with the user's PostHog host (e.g. us.posthog.com) for a clickable link."
                    ),
            })
        )
        .describe('Per-version assessment for all versions seen in the last 7 days.'),
    outdated_traffic_alerts: zod
        .array(
            zod.object({
                version: zod.string().describe('Outdated version handling significant traffic.'),
                threshold_percent: zod
                    .number()
                    .describe(
                        'Traffic-percentage threshold that triggered the alert (10% for most SDKs, 20% for web).'
                    ),
            })
        )
        .describe(
            'Outdated versions that handle a significant share of traffic (above the threshold). Not populated for mobile SDKs.'
        ),
})

export type SdkAssessmentApi = zod.input<typeof SdkAssessmentApi>
export type SdkAssessmentApiOutput = zod.output<typeof SdkAssessmentApi>

export const SdkHealthReportApi = zod.object({
    overall_health: zod
        .enum(['healthy', 'needs_attention'])
        .describe('\* `healthy` - healthy\n\* `needs_attention` - needs_attention')
        .describe(
            "'healthy' when no SDKs need updating, 'needs_attention' otherwise.\n\n\* `healthy` - healthy\n\* `needs_attention` - needs_attention"
        ),
    health: zod
        .enum(['success', 'warning', 'danger'])
        .describe('\* `success` - success\n\* `warning` - warning\n\* `danger` - danger')
        .describe(
            "UI-level status — 'success' when healthy, 'warning' when some SDKs are outdated, 'danger' when the majority are outdated.\n\n\* `success` - success\n\* `warning` - warning\n\* `danger` - danger"
        ),
    needs_updating_count: zod.number().describe('Number of SDKs that need updating.'),
    team_sdk_count: zod.number().describe('Number of distinct PostHog SDKs the project is actively using.'),
    sdks: zod
        .array(
            zod.object({
                lib: zod
                    .enum([
                        'web',
                        'posthog-ios',
                        'posthog-android',
                        'posthog-java',
                        'posthog-server',
                        'posthog-node',
                        'posthog-python',
                        'posthog-php',
                        'posthog-ruby',
                        'posthog-go',
                        'posthog-flutter',
                        'posthog-react-native',
                        'posthog-kmp',
                        'posthog-dotnet',
                        'posthog-elixir',
                    ])
                    .describe(
                        '\* `web` - web\n\* `posthog-ios` - posthog-ios\n\* `posthog-android` - posthog-android\n\* `posthog-java` - posthog-java\n\* `posthog-server` - posthog-server\n\* `posthog-node` - posthog-node\n\* `posthog-python` - posthog-python\n\* `posthog-php` - posthog-php\n\* `posthog-ruby` - posthog-ruby\n\* `posthog-go` - posthog-go\n\* `posthog-flutter` - posthog-flutter\n\* `posthog-react-native` - posthog-react-native\n\* `posthog-kmp` - posthog-kmp\n\* `posthog-dotnet` - posthog-dotnet\n\* `posthog-elixir` - posthog-elixir'
                    )
                    .describe(
                        "SDK identifier, e.g. 'web', 'posthog-python', 'posthog-node', 'posthog-ios'.\n\n\* `web` - web\n\* `posthog-ios` - posthog-ios\n\* `posthog-android` - posthog-android\n\* `posthog-java` - posthog-java\n\* `posthog-server` - posthog-server\n\* `posthog-node` - posthog-node\n\* `posthog-python` - posthog-python\n\* `posthog-php` - posthog-php\n\* `posthog-ruby` - posthog-ruby\n\* `posthog-go` - posthog-go\n\* `posthog-flutter` - posthog-flutter\n\* `posthog-react-native` - posthog-react-native\n\* `posthog-kmp` - posthog-kmp\n\* `posthog-dotnet` - posthog-dotnet\n\* `posthog-elixir` - posthog-elixir"
                    ),
                readable_name: zod
                    .string()
                    .describe(
                        "Human-readable SDK name matching the SDK Health UI (e.g. 'Python', 'Node.js', 'Web', 'iOS')."
                    ),
                latest_version: zod.string().describe('Most recent published version of this SDK.'),
                needs_updating: zod.boolean().describe('True if this SDK needs attention (is_outdated OR is_old).'),
                is_outdated: zod.boolean().describe('True if the primary in-use version is flagged as outdated.'),
                is_old: zod.boolean().describe('True if the primary in-use version is flagged as old by age alone.'),
                migration_required: zod
                    .boolean()
                    .describe(
                        'True when this SDK must be replaced by a supported successor rather than upgraded in place.'
                    ),
                severity: zod
                    .enum(['none', 'warning', 'danger'])
                    .describe('\* `none` - none\n\* `warning` - warning\n\* `danger` - danger')
                    .describe(
                        "UI severity badge — 'none' when healthy, 'warning' when outdated, 'danger' when the majority of team SDKs are outdated.\n\n\* `none` - none\n\* `warning` - warning\n\* `danger` - danger"
                    ),
                reason: zod
                    .string()
                    .describe(
                        'Per-SDK programmatic summary (used for ranking\/filtering). For user-facing copy, prefer releases[].status_reason (badge tooltip) and banners (top-level alert text) — those match the UI exactly.'
                    ),
                banners: zod
                    .array(zod.string())
                    .describe(
                        "Top-level alert sentences matching the SDK Health UI's 'Time for an update!' banner — one per outdated version with significant traffic. Quote verbatim when surfacing the headline to users."
                    ),
                releases: zod
                    .array(
                        zod.object({
                            version: zod.string().describe("In-use SDK version string, e.g. '1.298.0'."),
                            count: zod
                                .number()
                                .describe('Number of events captured with this version in the last 7 days.'),
                            max_timestamp: zod
                                .string()
                                .describe('Timestamp of the most recent event seen for this version (ISO 8601).'),
                            release_date: zod
                                .string()
                                .nullable()
                                .describe('When this version was published on GitHub (ISO 8601), or null if unknown.'),
                            days_since_release: zod
                                .number()
                                .nullable()
                                .describe('Days since this version was released, or null if unknown.'),
                            released_ago: zod
                                .string()
                                .nullable()
                                .describe(
                                    "Human-readable relative release age matching the UI (e.g. '5 months ago'). Null when release_date is unknown."
                                ),
                            is_outdated: zod
                                .boolean()
                                .describe('True when this version is flagged as outdated by smart-semver rules.'),
                            is_old: zod
                                .boolean()
                                .describe(
                                    'True when this version is flagged as old by age alone (separate from semver rules).'
                                ),
                            needs_updating: zod.boolean().describe('True if is_outdated OR is_old.'),
                            is_current_or_newer: zod
                                .boolean()
                                .describe(
                                    'True when this version equals or exceeds the latest known published version.'
                                ),
                            status_reason: zod
                                .string()
                                .describe(
                                    "Per-version badge tooltip text matching the SDK Health UI exactly. Quote verbatim when reporting to users. Varies by state: 'Released X ago. Upgrade recommended.' for outdated versions, 'You have the latest available.' for current versions, or 'Released X ago. Upgrading is a good idea, but it's not urgent yet.' for recent-but-behind versions."
                                ),
                            sql_query: zod
                                .string()
                                .describe(
                                    'SQL SELECT statement for drilling into events for this SDK version over the last 7 days. Suitable to pass to the execute-sql tool or to display as a copy-paste snippet.'
                                ),
                            activity_page_url: zod
                                .string()
                                .describe(
                                    "Relative URL path (starting with \/project\/{id}\/) for the Activity > Explore page pre-filtered to events captured with this lib and lib_version over the last 7 days. Combine with the user's PostHog host (e.g. us.posthog.com) for a clickable link."
                                ),
                        })
                    )
                    .describe('Per-version assessment for all versions seen in the last 7 days.'),
                outdated_traffic_alerts: zod
                    .array(
                        zod.object({
                            version: zod.string().describe('Outdated version handling significant traffic.'),
                            threshold_percent: zod
                                .number()
                                .describe(
                                    'Traffic-percentage threshold that triggered the alert (10% for most SDKs, 20% for web).'
                                ),
                        })
                    )
                    .describe(
                        'Outdated versions that handle a significant share of traffic (above the threshold). Not populated for mobile SDKs.'
                    ),
            })
        )
        .describe('Per-SDK health assessments.'),
})

export type SdkHealthReportApi = zod.input<typeof SdkHealthReportApi>
export type SdkHealthReportApiOutput = zod.output<typeof SdkHealthReportApi>
