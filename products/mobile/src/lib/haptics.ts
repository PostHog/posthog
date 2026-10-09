import * as Haptics from 'expo-haptics'
import { Platform } from 'react-native'

export type HapticKind = 'selection' | 'light' | 'success'

/** Fire-and-forget haptic feedback. A no-op on web, where expo-haptics has no backend. */
export function haptic(kind: HapticKind): void {
    if (Platform.OS === 'web') {
        return
    }
    const done = (): void => undefined
    if (kind === 'selection') {
        Haptics.selectionAsync().catch(done)
    } else if (kind === 'light') {
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(done)
    } else {
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(done)
    }
}
