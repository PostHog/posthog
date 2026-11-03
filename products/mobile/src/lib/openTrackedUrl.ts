import { Linking } from 'react-native'

import { type AnalyticsEvent, type AnalyticsProperties, actionTracker } from './analytics'

export async function openTrackedUrl(
    url: string,
    event: AnalyticsEvent,
    properties?: AnalyticsProperties
): Promise<boolean> {
    const record = actionTracker(properties)
    try {
        await Linking.openURL(url)
        record(event, { launch_result: 'accepted' })
        return true
    } catch {
        record('mobile_link_launch_failed', { link_event: event })
        return false
    }
}
