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

/** `tick`: a tap pins a point, or a scrub enters a new one. `hold`: a hold starts a scrub. `range`: a second finger lands. */
export type ChartHapticKind = 'tick' | 'hold' | 'range'

// A scrub across a dense chart crosses a bucket every few milliseconds. Ticks closer than this blur into a buzz.
const CHART_HAPTIC_MIN_GAP_MS = 30
let lastChartHapticAt = 0

/**
 * Chart feedback in each platform's own vocabulary: iOS selection and impact, Android's system segment tick and long
 * press. At most one fires per 30ms.
 */
export function chartHaptic(kind: ChartHapticKind): void {
    if (Platform.OS === 'web') {
        return
    }
    const now = Date.now()
    if (now - lastChartHapticAt < CHART_HAPTIC_MIN_GAP_MS) {
        return
    }
    lastChartHapticAt = now
    const done = (): void => undefined
    if (Platform.OS === 'android') {
        const type =
            kind === 'tick'
                ? Haptics.AndroidHaptics.Segment_Tick
                : kind === 'hold'
                  ? Haptics.AndroidHaptics.Long_Press
                  : Haptics.AndroidHaptics.Context_Click
        Haptics.performAndroidHapticsAsync(type).catch(done)
        return
    }
    if (kind === 'tick') {
        Haptics.selectionAsync().catch(done)
    } else {
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(done)
    }
}
