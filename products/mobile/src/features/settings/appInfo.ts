import * as Application from 'expo-application'
import Constants from 'expo-constants'
import * as Updates from 'expo-updates'

export interface AppInfo {
    version: string
    channel: string
}

/** Reads the app version and update channel. expo-updates has no channel in dev builds or on web. */
export function readAppInfo(): AppInfo {
    const version = Application.nativeApplicationVersion ?? Constants.expoConfig?.version ?? 'Unknown'
    const build = Application.nativeBuildVersion
    let channel: string | null = null
    try {
        channel = Updates.channel
    } catch {
        channel = null
    }
    return {
        version: build && build !== version ? `${version} (${build})` : version,
        channel: channel || (__DEV__ ? 'Development' : 'None'),
    }
}
