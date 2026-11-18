import * as Application from 'expo-application'
import Constants from 'expo-constants'

/** The app version, with the native build number when it differs. */
export function readAppVersion(): string {
    const version = Application.nativeApplicationVersion ?? Constants.expoConfig?.version ?? 'Unknown'
    const build = Application.nativeBuildVersion
    return build && build !== version ? `${version} (${build})` : version
}
