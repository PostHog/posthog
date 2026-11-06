import type { WebBreakdown, WebFilter, WebPropertyFilter, WebTileId } from '../views'

// The web analytics breakdown tiles and how a row becomes a filter. Ported from the web's
// `frontend/src/scenes/web-analytics/common.ts` (`webStatsBreakdownToPropertyName`, the drill-down maps) and the row
// click handler in `tiles/WebAnalyticsTile.tsx`.

export interface WebTileDef {
    id: WebTileId
    title: string
    /** The web's tabs, in the web's order. The first one is the tile's default. */
    tabs: readonly WebBreakdown[]
}

export const WEB_TILES: readonly WebTileDef[] = [
    { id: 'pages', title: 'Pages', tabs: ['Page', 'InitialPage', 'ExitPage', 'ExitClick'] },
    {
        id: 'sources',
        title: 'Sources',
        tabs: [
            'InitialChannelType',
            'InitialReferringDomain',
            'InitialUTMSource',
            'InitialUTMMedium',
            'InitialUTMCampaign',
        ],
    },
    { id: 'devices', title: 'Devices', tabs: ['DeviceType', 'Browser', 'OS', 'Viewport'] },
    { id: 'locations', title: 'Locations', tabs: ['Country', 'Region', 'City', 'Timezone', 'Language'] },
]

export function webTileDef(id: WebTileId): WebTileDef {
    return WEB_TILES.find((tile) => tile.id === id) ?? (WEB_TILES[0] as WebTileDef)
}

export const BREAKDOWN_LABELS: Record<WebBreakdown, string> = {
    Page: 'Path',
    InitialPage: 'Entry path',
    ExitPage: 'End path',
    ExitClick: 'Outbound clicks',
    InitialChannelType: 'Channel',
    InitialReferringDomain: 'Referring domain',
    InitialUTMSource: 'UTM source',
    InitialUTMMedium: 'UTM medium',
    InitialUTMCampaign: 'UTM campaign',
    DeviceType: 'Device type',
    Browser: 'Browser',
    OS: 'OS',
    Viewport: 'Viewport',
    Country: 'Country',
    Region: 'Region',
    City: 'City',
    Timezone: 'Time zone',
    Language: 'Language',
}

/** The web's drill-down after a row tap. Its other targets (referring URL, UTM content) are not phone tabs. */
export const DRILL_DOWN: Partial<Record<WebBreakdown, WebBreakdown>> = {
    InitialChannelType: 'InitialReferringDomain',
    InitialUTMSource: 'InitialUTMMedium',
    InitialUTMMedium: 'InitialUTMCampaign',
    Country: 'Region',
    Region: 'City',
    DeviceType: 'Browser',
    Browser: 'OS',
    OS: 'Viewport',
}

const PROPERTIES: Partial<Record<WebBreakdown, Pick<WebPropertyFilter, 'key' | 'type'>>> = {
    Page: { key: '$pathname', type: 'event' },
    InitialPage: { key: '$entry_pathname', type: 'session' },
    ExitPage: { key: '$end_pathname', type: 'session' },
    InitialChannelType: { key: '$channel_type', type: 'session' },
    InitialReferringDomain: { key: '$entry_referring_domain', type: 'session' },
    InitialUTMSource: { key: '$entry_utm_source', type: 'session' },
    InitialUTMMedium: { key: '$entry_utm_medium', type: 'session' },
    InitialUTMCampaign: { key: '$entry_utm_campaign', type: 'session' },
    DeviceType: { key: '$device_type', type: 'event' },
    Browser: { key: '$browser', type: 'event' },
    OS: { key: '$os', type: 'event' },
    Country: { key: '$geoip_country_code', type: 'event' },
    Region: { key: '$geoip_subdivision_1_code', type: 'event' },
    City: { key: '$geoip_city_name', type: 'event' },
    Language: { key: '$browser_language', type: 'event' },
}

/** False for outbound clicks: the web's outbound clicks table has no row filter either. */
export function breakdownFilters(breakdown: WebBreakdown): boolean {
    return breakdown === 'Viewport' || breakdown === 'Timezone' || PROPERTIES[breakdown] !== undefined
}

const NOT_SET = '(not set)'

// A small fallback for runtimes without `Intl.DisplayNames`, such as Hermes. Other codes show as the code.
const COUNTRY_NAMES: Record<string, string> = {
    AE: 'United Arab Emirates',
    AR: 'Argentina',
    AT: 'Austria',
    AU: 'Australia',
    BD: 'Bangladesh',
    BE: 'Belgium',
    BG: 'Bulgaria',
    BR: 'Brazil',
    CA: 'Canada',
    CH: 'Switzerland',
    CL: 'Chile',
    CN: 'China',
    CO: 'Colombia',
    CZ: 'Czechia',
    DE: 'Germany',
    DK: 'Denmark',
    EG: 'Egypt',
    ES: 'Spain',
    FI: 'Finland',
    FR: 'France',
    GB: 'United Kingdom',
    GR: 'Greece',
    HK: 'Hong Kong',
    HU: 'Hungary',
    ID: 'Indonesia',
    IE: 'Ireland',
    IL: 'Israel',
    IN: 'India',
    IT: 'Italy',
    JP: 'Japan',
    KE: 'Kenya',
    KR: 'South Korea',
    MX: 'Mexico',
    MY: 'Malaysia',
    NG: 'Nigeria',
    NL: 'Netherlands',
    NO: 'Norway',
    NZ: 'New Zealand',
    PH: 'Philippines',
    PK: 'Pakistan',
    PL: 'Poland',
    PT: 'Portugal',
    RO: 'Romania',
    RU: 'Russia',
    SA: 'Saudi Arabia',
    SE: 'Sweden',
    SG: 'Singapore',
    TH: 'Thailand',
    TR: 'Türkiye',
    TW: 'Taiwan',
    UA: 'Ukraine',
    US: 'United States',
    VN: 'Vietnam',
    ZA: 'South Africa',
}

const LANGUAGE_NAMES: Record<string, string> = {
    ar: 'Arabic',
    cs: 'Czech',
    da: 'Danish',
    de: 'German',
    el: 'Greek',
    en: 'English',
    es: 'Spanish',
    fi: 'Finnish',
    fr: 'French',
    he: 'Hebrew',
    hi: 'Hindi',
    id: 'Indonesian',
    it: 'Italian',
    ja: 'Japanese',
    ko: 'Korean',
    nl: 'Dutch',
    no: 'Norwegian',
    pl: 'Polish',
    pt: 'Portuguese',
    ro: 'Romanian',
    ru: 'Russian',
    sv: 'Swedish',
    th: 'Thai',
    tr: 'Turkish',
    uk: 'Ukrainian',
    vi: 'Vietnamese',
    zh: 'Chinese',
}

type DisplayNamesKind = 'region' | 'language'

const displayNames = new Map<DisplayNamesKind, ((code: string) => string | undefined) | null>()

function intlName(kind: DisplayNamesKind, code: string): string | undefined {
    if (!displayNames.has(kind)) {
        const DisplayNames = (Intl as { DisplayNames?: new (...args: unknown[]) => { of: (code: string) => string } })
            .DisplayNames
        try {
            const names = DisplayNames ? new DisplayNames(['en'], { type: kind, fallback: 'none' }) : null
            displayNames.set(kind, names ? (value) => names.of(value) : null)
        } catch {
            displayNames.set(kind, null)
        }
    }
    try {
        return displayNames.get(kind)?.(code) ?? undefined
    } catch {
        return undefined
    }
}

function isCountryCode(code: string): boolean {
    return /^[A-Z]{2}$/.test(code)
}

export function countryFlag(code: string): string {
    const upper = code.toUpperCase()
    if (!isCountryCode(upper)) {
        return ''
    }
    return String.fromCodePoint(...[...upper].map((letter) => 0x1f1e6 + letter.charCodeAt(0) - 65))
}

export function countryName(code: string): string {
    const upper = code.toUpperCase()
    return intlName('region', upper) ?? COUNTRY_NAMES[upper] ?? upper
}

function languageName(code: string): string {
    const lower = code.toLowerCase()
    return intlName('language', lower) ?? LANGUAGE_NAMES[lower] ?? code
}

function withFlag(code: unknown, text: string): string {
    const flag = typeof code === 'string' ? countryFlag(code) : ''
    return flag ? `${flag} ${text}` : text
}

/** The web's `toUtcOffsetFormat`: hours from UTC as "UTC", "UTC+2" or "UTC+5:30". */
export function utcOffsetLabel(hours: number): string {
    if (hours === 0) {
        return 'UTC'
    }
    const whole = Math.trunc(Math.abs(hours))
    const minutes = Math.round((Math.abs(hours) - whole) * 60)
    return `UTC${hours > 0 ? '+' : '-'}${whole}${minutes > 0 ? `:${String(minutes).padStart(2, '0')}` : ''}`
}

function decodePath(value: string): string {
    try {
        return decodeURIComponent(value)
    } catch {
        return value
    }
}

function finite(value: unknown): number | undefined {
    return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

export interface BreakdownValueLabel {
    label: string
    placeholder: boolean
}

export function breakdownValueLabel(breakdown: WebBreakdown, raw: unknown): BreakdownValueLabel {
    const plain = (label: string): BreakdownValueLabel => ({ label, placeholder: false })
    const missing: BreakdownValueLabel = {
        label: breakdown === 'InitialReferringDomain' ? '(direct)' : NOT_SET,
        placeholder: true,
    }
    switch (breakdown) {
        case 'Page':
        case 'InitialPage':
        case 'ExitPage':
            return typeof raw === 'string' ? plain(decodePath(raw)) : missing
        case 'Viewport':
            return Array.isArray(raw) && finite(raw[0]) !== undefined && finite(raw[1]) !== undefined
                ? plain(`${raw[0]} × ${raw[1]}`)
                : missing
        case 'Country':
            return typeof raw === 'string' && raw ? plain(withFlag(raw, countryName(raw))) : missing
        case 'Region': {
            if (!Array.isArray(raw)) {
                return missing
            }
            const name = typeof raw[2] === 'string' && raw[2] ? raw[2] : typeof raw[1] === 'string' ? raw[1] : null
            return { label: withFlag(raw[0], name ?? NOT_SET), placeholder: name === null }
        }
        case 'City': {
            if (!Array.isArray(raw)) {
                return missing
            }
            const name = typeof raw[1] === 'string' && raw[1] ? raw[1] : null
            return { label: withFlag(raw[0], name ?? NOT_SET), placeholder: name === null }
        }
        case 'Timezone': {
            const hours = finite(raw)
            return hours === undefined ? missing : plain(utcOffsetLabel(hours))
        }
        case 'InitialReferringDomain':
            // Sessions without a referrer store `$direct`.
            return typeof raw === 'string' && raw && raw !== '$direct' ? plain(raw) : missing
        case 'Language': {
            if (typeof raw !== 'string' || !raw) {
                return missing
            }
            const [language, country] = raw.split('-')
            if (!language) {
                return missing
            }
            const countryCode = country?.match(/[A-Z]{2}/)?.[0] ?? ''
            return plain(withFlag(countryCode, languageName(language)))
        }
        default:
            if (typeof raw === 'string' && raw) {
                return plain(raw)
            }
            return typeof raw === 'number' ? plain(String(raw)) : missing
    }
}

function exact(key: string, type: WebPropertyFilter['type'], value: string | number): WebPropertyFilter {
    return { key, type, operator: 'exact', value }
}

/** As on the web, a missing value filters by "is not set" and a time zone by the browser's offset in minutes. */
export function breakdownFilter(breakdown: WebBreakdown, raw: unknown): WebFilter | null {
    const label = BREAKDOWN_LABELS[breakdown]
    const value = breakdownValueLabel(breakdown, raw).label
    switch (breakdown) {
        case 'Viewport': {
            const width = Array.isArray(raw) ? finite(raw[0]) : undefined
            const height = Array.isArray(raw) ? finite(raw[1]) : undefined
            if (width === undefined || height === undefined) {
                return null
            }
            return {
                id: '$viewport',
                label,
                value,
                properties: [exact('$viewport_width', 'event', width), exact('$viewport_height', 'event', height)],
            }
        }
        case 'Timezone': {
            const hours = finite(raw)
            if (hours === undefined) {
                return null
            }
            return {
                id: '$timezone_offset',
                label,
                value,
                properties: [exact('$timezone_offset', 'event', -(hours * 60))],
            }
        }
        case 'Region':
        case 'City': {
            const part = Array.isArray(raw) ? raw[1] : undefined
            const property = PROPERTIES[breakdown]
            if (!property || typeof part !== 'string' || !part) {
                return null
            }
            return { id: property.key, label, value, properties: [exact(property.key, property.type, part)] }
        }
        default: {
            const property = PROPERTIES[breakdown]
            if (!property) {
                return null
            }
            const language = breakdown === 'Language' && typeof raw === 'string' ? raw.split('-', 1)[0] : undefined
            if (raw === null || raw === undefined || raw === '' || language === '') {
                return {
                    id: property.key,
                    label,
                    value,
                    properties: [{ key: property.key, type: property.type, operator: 'is_not_set' }],
                }
            }
            if (typeof raw !== 'string' && typeof raw !== 'number') {
                return null
            }
            // The stats query groups by the base language and appends the most common region for display.
            const filter = language
                ? {
                      ...property,
                      operator: 'regex' as const,
                      value: `^${language.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(-|$)`,
                  }
                : exact(property.key, property.type, raw)
            return { id: property.key, label, value, properties: [filter] }
        }
    }
}

function sameFilter(left: WebFilter, right: WebFilter): boolean {
    return left.id === right.id && JSON.stringify(left.properties) === JSON.stringify(right.properties)
}

export interface FilterChange {
    filters: WebFilter[]
    /** `removed` when the tap matched the active filter, which a second tap turns off, as on the web. */
    kind: 'added' | 'replaced' | 'removed'
}

export function toggleFilter(filters: readonly WebFilter[], filter: WebFilter): FilterChange {
    const index = filters.findIndex((candidate) => candidate.id === filter.id)
    const current = filters[index]
    if (!current) {
        return { filters: [...filters, filter], kind: 'added' }
    }
    if (sameFilter(current, filter)) {
        return { filters: filters.filter((_, position) => position !== index), kind: 'removed' }
    }
    return {
        filters: filters.map((candidate, position) => (position === index ? filter : candidate)),
        kind: 'replaced',
    }
}
