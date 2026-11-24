import type { ReactElement } from 'react'
import { Text, View } from 'react-native'
import Animated, { FadeIn, FadeOut, interpolate, useAnimatedStyle } from 'react-native-reanimated'

import { ArrowDownIcon } from '@/ui/icons/ArrowDownIcon'
import { FastForwardIcon } from '@/ui/icons/FastForwardIcon'
import { createStyles } from '@/ui/theme'

import { holdPull, useFeedHold } from './feedHoldStore'
import { feedColors } from './feedStyle'
import { HOLD_PULL } from './holdLock'

/** The chip and the pull hint while a hold is down. The haptics, not the text, tell the finger it passed the threshold. */
export function HoldHud({ top }: { top: number }): ReactElement | null {
    const styles = useStyles()
    const hold = useFeedHold((state) => state.hold)
    // The chip follows the finger a little, and less once the pull passes the threshold, so the pull feels like a spring.
    const follow = useAnimatedStyle(() => {
        const pull = holdPull.value
        const y = pull < HOLD_PULL ? pull * 0.4 : HOLD_PULL * 0.4 + Math.min(pull - HOLD_PULL, 80) * 0.12
        return { transform: [{ translateY: y }] }
    })
    const progress = useAnimatedStyle(() => ({
        transform: [{ scaleX: interpolate(holdPull.value, [0, HOLD_PULL], [0, 1], 'clamp') }],
    }))

    if (!hold) {
        return null
    }
    return (
        <Animated.View
            entering={FadeIn.duration(120)}
            exiting={FadeOut.duration(120)}
            style={[styles.hud, { top }, follow]}
            pointerEvents="none"
            testID="feed-hold-hud"
        >
            <View style={styles.chip}>
                <FastForwardIcon size={17} color={feedColors.stage} />
                <Text style={styles.chipText}>{`${hold.rate}x`}</Text>
            </View>
            <View style={[styles.hint, hold.armed && styles.hintArmed]}>
                {hold.armed ? null : <Animated.View style={[styles.hintFill, progress]} />}
                <ArrowDownIcon size={15} color={feedColors.text} />
                <Text style={styles.hintText}>{hold.locked ? 'Pull down to unlock' : 'Pull down to lock'}</Text>
            </View>
        </Animated.View>
    )
}

const useStyles = createStyles(() => ({
    hud: {
        position: 'absolute',
        alignSelf: 'center',
        alignItems: 'center',
        gap: 8,
    },
    chip: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 6,
        height: 36,
        paddingLeft: 12,
        paddingRight: 15,
        borderRadius: 18,
        backgroundColor: 'rgba(255,255,255,0.95)',
    },
    chipText: {
        fontSize: 16,
        fontWeight: '700',
        color: '#1F1F1C',
    },
    hint: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 6,
        height: 30,
        paddingLeft: 10,
        paddingRight: 12,
        borderRadius: 15,
        overflow: 'hidden',
        backgroundColor: 'rgba(0,0,0,0.62)',
    },
    hintArmed: {
        backgroundColor: feedColors.accent,
    },
    hintFill: {
        position: 'absolute',
        top: 0,
        bottom: 0,
        left: 0,
        right: 0,
        transformOrigin: 'left',
        backgroundColor: 'rgba(255,255,255,0.2)',
    },
    hintText: {
        fontSize: 13,
        fontWeight: '600',
        color: feedColors.text,
    },
}))
