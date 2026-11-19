import type { ComponentType, ReactElement, ReactNode } from 'react'
import { Text, View } from 'react-native'
import Animated, { useAnimatedStyle, withTiming } from 'react-native-reanimated'

import { ChatBubbleIcon } from '@/ui/icons/ChatBubbleIcon'
import { ShareIcon } from '@/ui/icons/ShareIcon'
import type { IconProps } from '@/ui/icons/types'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles } from '@/ui/theme'

import { feedColors, feedTextShadow } from './feedStyle'

interface FeedRailProps {
    /** The rate playing now: a hold's or a lock's when one is on, else the set speed. */
    speed: number
    speedOn: boolean
    /** A hold fades every button but Speed, which shows the hold's rate. */
    speedOnly: boolean
    onSpeed: () => void
    onChat?: () => void
    onShare?: () => void
}

export function speedLabel(speed: number): string {
    return `${speed}x`
}

export function FeedRail({ speed, speedOn, speedOnly, onSpeed, onChat, onShare }: FeedRailProps): ReactElement {
    const styles = useStyles()
    const label = speedLabel(speed)
    const others = useAnimatedStyle(
        () => ({ opacity: withTiming(speedOnly ? 0 : 1, { duration: speedOnly ? 120 : 180 }) }),
        [speedOnly]
    )
    return (
        <View style={styles.rail} pointerEvents="box-none">
            <RailButton
                label="Speed"
                accessibilityLabel={`Speed, ${label}`}
                on={speedOn}
                onPress={onSpeed}
                testID="feed-speed"
            >
                <Text style={[styles.speed, label.length > 3 && styles.speedSmall, speedOn && styles.speedOn]}>
                    {label}
                </Text>
            </RailButton>
            <Animated.View style={[styles.rail, others]} pointerEvents="box-none">
                {onChat ? <RailButton label="Chat" Icon={ChatBubbleIcon} onPress={onChat} testID="feed-chat" /> : null}
                {onShare ? <RailButton label="Share" Icon={ShareIcon} onPress={onShare} testID="feed-share" /> : null}
            </Animated.View>
        </View>
    )
}

interface RailButtonProps {
    label: string
    accessibilityLabel?: string
    Icon?: ComponentType<IconProps>
    on?: boolean
    children?: ReactNode
    onPress: () => void
    testID: string
}

function RailButton({
    label,
    accessibilityLabel,
    Icon,
    on = false,
    children,
    onPress,
    testID,
}: RailButtonProps): ReactElement {
    const styles = useStyles()
    return (
        <Pressable44
            onPress={onPress}
            accessibilityLabel={accessibilityLabel ?? label}
            accessibilityState={{ selected: on }}
            style={styles.button}
            pressedStyle={styles.pressed}
            haptic="selection"
            testID={testID}
        >
            {({ pressed }) => (
                <>
                    <View style={[styles.circle, on && styles.circleOn, pressed && styles.circlePressed]}>
                        {Icon ? <Icon size={22} color={on ? feedColors.stage : feedColors.text} /> : children}
                    </View>
                    <Text style={styles.label} numberOfLines={1}>
                        {label}
                    </Text>
                </>
            )}
        </Pressable44>
    )
}

const useStyles = createStyles(() => ({
    rail: {
        alignItems: 'center',
        gap: 10,
    },
    button: {
        alignItems: 'center',
        gap: 5,
        width: 92,
    },
    pressed: {
        opacity: 0.85,
    },
    circle: {
        width: 48,
        height: 48,
        borderRadius: 24,
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: feedColors.glass,
        borderWidth: 1,
        borderColor: feedColors.glassBorder,
    },
    circleOn: {
        backgroundColor: feedColors.text,
        borderColor: feedColors.text,
    },
    circlePressed: {
        backgroundColor: feedColors.glassPressed,
    },
    label: {
        fontSize: 12,
        fontWeight: '600',
        color: feedColors.text,
        textAlign: 'center',
        ...feedTextShadow,
    },
    speed: {
        fontSize: 15,
        fontWeight: '700',
        color: feedColors.text,
    },
    speedSmall: {
        fontSize: 13,
    },
    speedOn: {
        color: feedColors.stage,
    },
}))
