export interface BreakdownPreset {
    property: string
    title: string
}

export const LIMIT_ITEMS = 3
export const BREAKDOWN_DETAILS_LIMIT = 100

// Each property adds an arrayJoin fan-out, so cap event-derived properties to keep query cost bounded.
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
    MiniBreakdownsPropertySelected: 'error tracking mini breakdowns property selected',
}
