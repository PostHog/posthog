import type { IdentityMatchingLinkApi, IdentityMatchingPersonApi } from './generated/api.schemas'

/** Very permissive email format — matches the person-utils pattern. */
const EMAIL_REGEX = /.+@.+\..+/i

/** Returns an email if the identifier looks like one, otherwise null. */
export function extractEmail(identifier: string): string | null {
    return EMAIL_REGEX.test(identifier) ? identifier : null
}

/**
 * Build a PersonDisplay-shaped object for one side of a link, preferring the resolved person's real
 * email/name and falling back to a distinct ID that already looks like an email. This is what makes
 * people show by their email everywhere — table, dialog, and paid attribution.
 */
export function linkPersonDisplay(
    person: IdentityMatchingPersonApi | null | undefined,
    distinctId: string
): { properties?: Record<string, unknown>; distinct_id: string } {
    const email = person?.email ?? extractEmail(distinctId)
    const properties: Record<string, unknown> = {}
    if (email) {
        properties.email = email
    }
    if (person?.name) {
        properties.name = person.name
    }
    return Object.keys(properties).length > 0 ? { properties, distinct_id: distinctId } : { distinct_id: distinctId }
}

/** A non-empty property value to show, or null when the person is missing or the value is unset. */
export function personField(
    person: IdentityMatchingPersonApi | null | undefined,
    key: keyof IdentityMatchingPersonApi
): string | null {
    const value = person?.[key]
    return value != null && value !== '' ? String(value) : null
}

export interface PersonFieldSpec {
    key: keyof IdentityMatchingPersonApi
    label: string
}

/** Location/device fields shown side-by-side for match validation — they mirror the match signals. */
export const PERSON_SIGNAL_FIELDS: PersonFieldSpec[] = [
    { key: 'city', label: 'City' },
    { key: 'country', label: 'Country' },
    { key: 'browser', label: 'Browser' },
    { key: 'os', label: 'OS' },
    { key: 'device_type', label: 'Device' },
    { key: 'timezone', label: 'Timezone' },
]

/** Campaign attribution fields — surfaced prominently in the paid attribution tab. */
export const PERSON_CAMPAIGN_FIELDS: PersonFieldSpec[] = [
    { key: 'utm_source', label: 'Source' },
    { key: 'utm_medium', label: 'Medium' },
    { key: 'utm_campaign', label: 'Campaign' },
    { key: 'referring_domain', label: 'Referrer' },
    { key: 'gclid', label: 'Google click ID' },
]

/** True when this person carries any campaign attribution worth showing. */
export function hasCampaign(person: IdentityMatchingPersonApi | null | undefined): boolean {
    return PERSON_CAMPAIGN_FIELDS.some((field) => personField(person, field.key) !== null)
}

export type Tier = 'high' | 'medium' | 'low'

export type SignalCategory = 'network' | 'device' | 'behavior' | 'attribution'

export interface Signal {
    category: SignalCategory
    label: string
    /** Plain-English explanation of what this signal means and why it matters. */
    description: string
    /** How much this signal contributes to confidence: 1 (weak) to 3 (strong). */
    strength: number
}

export const CATEGORY_ORDER: SignalCategory[] = ['network', 'device', 'behavior', 'attribution']

export const CATEGORY_LABELS: Record<SignalCategory, string> = {
    network: 'Shared network',
    device: 'Matching devices',
    behavior: 'Browsing patterns',
    attribution: 'Paid attribution',
}

export const CATEGORY_DESCRIPTIONS: Record<SignalCategory, string> = {
    network: 'Both identities were seen on the same network — the strongest indicator they are the same person.',
    device: 'Both identities used similar hardware or software, suggesting the same physical device or user.',
    behavior: 'Both identities visited similar pages at similar times, suggesting the same browsing session.',
    attribution:
        'A paid ad click by the anonymous visitor can now be attributed to the identified person — recovering lost attribution data.',
}

/**
 * Decompose a link's evidence fields into categorized, weighted signals.
 * Signal strengths are based on how predictive each signal is in the scoring models.
 */
export function extractSignals(link: IdentityMatchingLinkApi): Signal[] {
    const signals: Signal[] = [
        {
            category: 'network',
            label: `${link.shared_ip_days} shared IP-day${link.shared_ip_days === 1 ? '' : 's'}`,
            description:
                'Both identities were seen on the same IP address on the same day(s). This is the strongest signal — it means they were likely on the same network (home, office, or mobile).',
            strength: 3,
        },
        {
            category: 'network',
            label: `${link.shared_ips} shared IP${link.shared_ips === 1 ? '' : 's'}`,
            description: 'They shared multiple distinct IP addresses, further reinforcing the connection.',
            strength: 2,
        },
        {
            category: 'network',
            label: 'Small IP block (household)',
            description:
                'The shared IP had very few other devices on it, suggesting a household or personal network rather than a shared office or VPN.',
            strength: 2,
        },
        {
            category: 'network',
            label: 'Same city',
            description: 'Both identities were geolocated to the same city.',
            strength: 1,
        },
        {
            category: 'device',
            label: 'Same user agent',
            description:
                'Both identities sent an identical browser user agent string — same browser version, OS, and device. This strongly suggests the same device.',
            strength: 3,
        },
        {
            category: 'device',
            label: 'Webview + same UA',
            description:
                'The anonymous visitor came from an in-app webview, and the user agent matches the identified person — common when someone clicks a link inside an app.',
            strength: 2,
        },
        {
            category: 'device',
            label: 'Mobile + desktop pair',
            description:
                'One identity is mobile and the other is desktop — a common pattern for the same person using multiple devices on the same network.',
            strength: 1,
        },
        {
            category: 'device',
            label: 'Same timezone',
            description: 'Both identities reported the same browser timezone.',
            strength: 1,
        },
        {
            category: 'device',
            label: 'Same language',
            description: 'Both identities had the same browser language setting.',
            strength: 1,
        },
        {
            category: 'behavior',
            label: `${Math.round(link.avg_path_jaccard * 100)}% path overlap`,
            description:
                'On the days they shared an IP, both identities visited many of the same pages — suggesting the same person browsing across devices.',
            strength: 2,
        },
        {
            category: 'behavior',
            label: `${link.days_overlap} day${link.days_overlap === 1 ? '' : 's'} of overlap`,
            description: 'They were seen on the same network on multiple distinct days.',
            strength: 1,
        },
        {
            category: 'attribution',
            label: 'New paid touch recovered',
            description:
                'The anonymous visitor arrived via a paid ad click (e.g., Google Ads). This match links that ad spend to the identified person, recovering attribution that would otherwise be lost.',
            strength: 3,
        },
        {
            category: 'attribution',
            label: 'Paid continuity',
            description:
                'Both the anonymous visitor and the identified person had paid ad click IDs — the match confirms they are the same person across the ad journey.',
            strength: 2,
        },
    ]

    const isActive = (s: Signal): boolean => {
        switch (s.label) {
            case `${link.shared_ip_days} shared IP-day${link.shared_ip_days === 1 ? '' : 's'}`:
                return link.shared_ip_days > 0
            case `${link.shared_ips} shared IP${link.shared_ips === 1 ? '' : 's'}`:
                return link.shared_ips > 1
            case 'Small IP block (household)':
                return link.min_ip_block_size <= 3 && link.shared_ip_days > 0
            case 'Same city':
                return link.geo_city_match
            case 'Same user agent':
                return link.ua_exact_match
            case 'Webview + same UA':
                return link.orphan_is_webview && link.ua_exact_match
            case 'Mobile + desktop pair':
                return link.device_type_complement
            case 'Same timezone':
                return link.timezone_match
            case 'Same language':
                return link.language_match
            case `${Math.round(link.avg_path_jaccard * 100)}% path overlap`:
                return link.avg_path_jaccard > 0
            case `${link.days_overlap} day${link.days_overlap === 1 ? '' : 's'} of overlap`:
                return link.days_overlap > 0
            case 'New paid touch recovered':
                return link.orphan_paid_touch && !link.anchor_paid_touch
            case 'Paid continuity':
                return link.orphan_paid_touch && link.anchor_paid_touch
            default:
                return false
        }
    }

    return signals.filter(isActive)
}

/**
 * Normalize a score to a 0-1 confidence value.
 * - logreg_v1: already 0-1
 * - rules_v1: unbounded weighted sum — normalize against a practical max of ~10
 */
export function normalizedScore(link: IdentityMatchingLinkApi): number {
    if (link.model_version === 'logreg_v1') {
        return Math.min(link.score, 1)
    }
    return Math.min(link.score / 10, 1)
}

export interface TierStats {
    high: number
    medium: number
    low: number
    total: number
    paidTouches: number
}

export function computeTierStats(links: IdentityMatchingLinkApi[]): TierStats {
    const stats: TierStats = { high: 0, medium: 0, low: 0, total: links.length, paidTouches: 0 }
    for (const link of links) {
        stats[link.tier as Tier]++
        if (link.orphan_paid_touch && !link.anchor_paid_touch) {
            stats.paidTouches++
        }
    }
    return stats
}
