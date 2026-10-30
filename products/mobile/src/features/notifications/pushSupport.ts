import Constants, { ExecutionEnvironment } from 'expo-constants'
import * as Device from 'expo-device'
import { Platform } from 'react-native'

/** `expo_go`: Expo Go would register its own app's token, so pushes for this app never arrive. */
export type PushUnavailableReason = 'web' | 'simulator' | 'expo_go'

export function pushUnavailableReason(): PushUnavailableReason | null {
    if (Platform.OS === 'web') {
        return 'web'
    }
    if (Constants.executionEnvironment === ExecutionEnvironment.StoreClient) {
        return 'expo_go'
    }
    if (!Device.isDevice) {
        return 'simulator'
    }
    return null
}

export function notificationsSupported(): boolean {
    return Platform.OS !== 'web'
}
