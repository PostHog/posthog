import { type ReactElement, useEffect, useState } from 'react'
import { Text, View } from 'react-native'
import Animated, { FadeIn, FadeOut, interpolate, useAnimatedStyle } from 'react-native-reanimated'

import { ArrowDownIcon } from '@/ui/icons/ArrowDownIcon'
import { FastForwardIcon } from '@/ui/icons/FastForwardIcon'
import { LockIcon } from '@/ui/icons/LockIcon'
import { UnlockIcon } from '@/ui/icons/UnlockIcon'
import { createStyles } from '@/ui/theme'

import { holdPull, useFeedHold } from './feedHoldStore'
import { feedColors } from './feedStyle'
import { HOLD_PULL } from './holdLock'

const NOTICE_MS = 1600

function hintText(locked: boolean, armed: boolean): string {
    if (armed) {
        return locked ? 'Release to unlock' : 'Release to lock'
    }
    return locked ? 'Pull down to unlock' : 'Pull down to lock'
}

/** The chip and the pull hint while a hold is down, and the short notice after a pull locks or unlocks. */
export function HoldHud({ top }: { top: number }): ReactElement | null {
    const styles = useStyles()
    const hold = useFeedHold((state) => state.hold)
    const notice = useFeedHold((state) => state.notice)
    const [shownNotice, setShownNotice] = useState<number | null>(null)
    useEffect(() => {
        if (!notice) {
            return undefined
        }
        setShownNotice(notice.id)
        const timer = setTimeout(() => setShownNotice(null), NOTICE_MS)
        return () => clearTimeout(timer)
    }, [notice])
    // The chip follows the finger a little, and less once the pull passes the threshold, so the pull feels like a spring.
    const follow = useAnimatedStyle(() => {
        const pull = holdPull.value
        const y = pull < HOLD_PULL ? pull * 0.4 : HOLD_PULL * 0.4 + Math.min(pull - HOLD_PULL, 80) * 0.12
        return { transform: [{ translateY: y }] }
    })
    const progress = useAnimatedStyle(() => ({
        transform: [{ scaleX: interpolate(holdPull.value, [0, HOLD_PULL], [0, 1], 'clamp') }],
    }))

    if (hold) {
        const Hint = hold.armed ? (hold.locked ? UnlockIcon : LockIcon) : ArrowDownIcon
        return (
            <Animated.View
                entering={FadeIn.duration(120)}
                exiting={FadeOut.duration(120)}
                style={[styles.hud, { top }, follow]}
                pointerEvents="none"
                testID="feed-hold-hud"
            >
                <View style={styles.chip}>
                    {hold.locked ? (
                        <LockIcon size={17} color={feedColors.stage} />
                    ) : (
                        <FastForwardIcon size={17} color={feedColors.stage} />
                    )}
                    <Text style={styles.chipText}>{`${hold.rate}x`}</Text>
                </View>
                <View style={[styles.hint, hold.armed && styles.hintArmed]}>
                    {hold.armed ? null : <Animated.View style={[styles.hintFill, progress]} />}
                    <Hint size={15} color={feedColors.text} />
                    <Text style={styles.hintText}>{hintText(hold.locked, hold.armed)}</Text>
                </View>
            </Animated.View>
        )
    }
    if (notice && shownNotice === notice.id) {
        return (
            <Animated.View
                key={notice.id}
                entering={FadeIn.duration(140)}
                exiting={FadeOut.duration(180)}
                style={[styles.hud, { top: top + 54 }]}
                pointerEvents="none"
                testID="feed-lock-notice"
            >
                <View style={styles.notice}>
                    <Text style={styles.noticeText}>{notice.text}</Text>
                </View>
            </Animated.View>
        )
    }
    return null
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
    notice: {
        height: 36,
        paddingHorizontal: 16,
        borderRadius: 18,
        justifyContent: 'center',
        backgroundColor: feedColors.glassStrong,
        borderWidth: 1,
        borderColor: feedColors.glassBorder,
    },
    noticeText: {
        fontSize: 15,
        fontWeight: '700',
        color: feedColors.text,
    },
}))
