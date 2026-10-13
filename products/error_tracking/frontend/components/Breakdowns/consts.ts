import { BUILT_IN_ERROR_TRACKING_PROPERTIES } from '../builtInProperties'

export interface BreakdownPreset {
    property: string
    title: string
}

export const LIMIT_ITEMS = 3
export const BREAKDOWN_DETAILS_LIMIT = 100

// Each property adds an arrayJoin fan-out, so cap event-derived properties to keep query cost bounded.
export const MAX_SELECTED_EVENT_BREAKDOWN_PROPERTIES = 10

const DEFAULT_BREAKDOWN_PROPERTY_NAMES = new Set([
    '$browser',
    '$device_type',
    '$os',
    '$pathname',
    '$user_id',
    '$ip',
    '$geoip_country_name',
    '$geoip_city_name',
])

export const BREAKDOWN_PRESETS: BreakdownPreset[] = BUILT_IN_ERROR_TRACKING_PROPERTIES.filter(({ property }) =>
    DEFAULT_BREAKDOWN_PROPERTY_NAMES.has(property)
).map(({ property, title }) => ({ property, title }))

export const BreakdownsEvents = {
    MiniBreakdownsLoaded: 'error tracking mini breakdowns loaded',
    MiniBreakdownsPropertySelected: 'error tracking mini breakdowns property selected',
}
