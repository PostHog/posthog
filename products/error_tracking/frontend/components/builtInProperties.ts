export interface BuiltInErrorTrackingProperty {
    property: string
    title: string
    versionProperty?: string
    /**
     * Read in place of `property` whenever it holds a value, for SDKs that report the same thing
     * under another key. `property` stays the canonical key, so breakdown presets are unaffected.
     */
    preferredProperty?: string
}

export const BUILT_IN_ERROR_TRACKING_PROPERTIES: BuiltInErrorTrackingProperty[] = [
    { property: '$browser', title: 'Browser', versionProperty: '$browser_version' },
    { property: '$device_type', title: 'Device type' },
    // $os_name has to win here as well as in getExceptionAttributes, or one exception reports a
    // different platform in the properties table than in the release popover.
    {
        property: '$os',
        title: 'Operating system',
        versionProperty: '$os_version',
        preferredProperty: '$os_name',
    },
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

/** The property key to read a built-in entry's value and filter from. */
export function resolveBuiltInProperty(
    properties: Record<string, unknown> | undefined,
    { property, preferredProperty }: BuiltInErrorTrackingProperty
): string {
    if (!preferredProperty) {
        return property
    }
    const preferred = properties?.[preferredProperty]
    return preferred === undefined || preferred === null || preferred === '' ? property : preferredProperty
}
