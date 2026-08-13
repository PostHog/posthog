export interface BreakdownPreset {
    property: string
    title: string
    removable?: boolean
}

export const LIMIT_ITEMS = 3
export const BREAKDOWN_DETAILS_LIMIT = 100

// Each breakdown property adds an arrayJoin fan-out to the query, so the auto-derived list from the
// selected event is capped to keep the page-load cost from scaling with the event's schema width.
// Any property beyond the cap stays reachable through the property picker.
export const MAX_SELECTED_EVENT_BREAKDOWN_PROPERTIES = 10

export const BREAKDOWN_PRESETS: BreakdownPreset[] = [
    { property: '$browser', title: 'Browser' },
    { property: '$device_type', title: 'Device type' },
    { property: '$os', title: 'Operating system' },
    { property: '$pathname', title: 'Path' },
    { property: '$user_id', title: 'User ID' },
    { property: '$ip', title: 'IP address' },
]

export const BreakdownsEvents = {
    MiniBreakdownsLoaded: 'error tracking mini breakdowns loaded',
}
