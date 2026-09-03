export interface BuiltInErrorTrackingProperty {
    property: string
    title: string
    versionProperty?: string
}

export const BUILT_IN_ERROR_TRACKING_PROPERTIES: BuiltInErrorTrackingProperty[] = [
    { property: '$browser', title: 'Browser', versionProperty: '$browser_version' },
    { property: '$device_type', title: 'Device type' },
    { property: '$os', title: 'Operating system', versionProperty: '$os_version' },
    { property: '$pathname', title: 'Path' },
    { property: '$user_id', title: 'User ID' },
    { property: '$ip', title: 'IP address' },
    { property: '$geoip_country_name', title: 'Country' },
    { property: '$geoip_city_name', title: 'City' },
    { property: '$exception_level', title: 'Level' },
    { property: '$lib', title: 'Library', versionProperty: '$lib_version' },
    { property: '$app_namespace', title: 'App', versionProperty: '$app_version' },
    { property: '$current_url', title: 'Current URL' },
]
