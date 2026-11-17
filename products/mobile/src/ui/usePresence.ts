import { useEffect, useState } from 'react'
import { Easing, type SharedValue, useReducedMotion, useSharedValue, withTiming } from 'react-native-reanimated'

import { motion } from './tokens'

export interface Presence {
    /** Keep the overlay in the tree while this is true, including during the exit animation. */
    mounted: boolean
    progress: SharedValue<number>
}

export type PresenceCurve = 'easeOut' | 'emphasized'

export function usePresence(visible: boolean, duration: number, curve: PresenceCurve = 'easeOut'): Presence {
    const reduceMotion = useReducedMotion()
    const [mounted, setMounted] = useState(visible)
    const progress = useSharedValue(0)

    useEffect(() => {
        const ms = reduceMotion ? 0 : duration
        const points = curve === 'emphasized' ? motion.emphasizedBezier : motion.easeOutBezier
        const easing = Easing.bezier(points[0], points[1], points[2], points[3])
        if (visible) {
            setMounted(true)
            progress.value = withTiming(1, { duration: ms, easing })
            return undefined
        }
        progress.value = withTiming(0, { duration: ms, easing })
        const timer = setTimeout(() => setMounted(false), ms)
        return () => clearTimeout(timer)
    }, [visible, duration, curve, reduceMotion, progress])

    return { mounted, progress }
}
