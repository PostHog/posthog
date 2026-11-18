import { isGlassEffectAPIAvailable, isLiquidGlassAvailable } from 'expo-glass-effect'
import { useEffect, useState } from 'react'
import { AccessibilityInfo } from 'react-native'

/**
 * Whether a floating card can draw Liquid Glass: the system has it (iOS 26 and later), and neither Reduce Transparency
 * nor Increase Contrast is on. The answer is false until both settings are read, so a person who turned them on never
 * sees a glass card first.
 */
export function useLiquidGlass(): boolean {
    // Some iOS 26 betas report glass but lack the API, and a glass view crashes there.
    const supported = isLiquidGlassAvailable() && isGlassEffectAPIAvailable()
    const [reduceTransparency, setReduceTransparency] = useState<boolean | null>(null)
    const [increaseContrast, setIncreaseContrast] = useState<boolean | null>(null)

    useEffect(() => {
        if (!supported) {
            return undefined
        }
        let mounted = true
        void AccessibilityInfo.isReduceTransparencyEnabled().then((enabled) => {
            if (mounted) setReduceTransparency(enabled)
        })
        void AccessibilityInfo.isDarkerSystemColorsEnabled().then((enabled) => {
            if (mounted) setIncreaseContrast(enabled)
        })
        const subscriptions = [
            AccessibilityInfo.addEventListener('reduceTransparencyChanged', setReduceTransparency),
            AccessibilityInfo.addEventListener('darkerSystemColorsChanged', setIncreaseContrast),
        ]
        return () => {
            mounted = false
            for (const subscription of subscriptions) subscription.remove()
        }
    }, [supported])

    return supported && reduceTransparency === false && increaseContrast === false
}
