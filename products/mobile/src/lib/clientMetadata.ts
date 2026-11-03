import * as Application from 'expo-application'
import Constants from 'expo-constants'
import { Platform } from 'react-native'

import { analyticsSessionId } from './analytics'
import { updateId } from './environment'

export function clientRequestHeaders(actionId: string): Record<string, string> {
    const version = Application.nativeApplicationVersion ?? Constants.expoConfig?.version ?? 'unknown'
    const sessionId = analyticsSessionId()
    return {
        'X-PostHog-Client-Platform': 'mobile',
        'X-PostHog-Client-OS': Platform.OS,
        'User-Agent': `posthog/mobile.hog.dev; version: ${version}`,
        'X-PostHog-Client-Action-Id': actionId,
        'X-PostHog-App-Version': version,
        ...(Application.nativeBuildVersion ? { 'X-PostHog-App-Build': Application.nativeBuildVersion } : {}),
        ...(updateId ? { 'X-PostHog-Update-Id': updateId } : {}),
        ...(sessionId ? { 'X-Posthog-Session-Id': sessionId } : {}),
    }
}
