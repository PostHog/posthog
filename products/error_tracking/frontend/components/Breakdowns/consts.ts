export interface BreakdownPreset {
    property: string
    title: string
    removable?: boolean
}

export const LIMIT_ITEMS = 3

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
