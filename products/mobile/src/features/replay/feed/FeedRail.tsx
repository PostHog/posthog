import type { ComponentType, ReactElement, ReactNode } from 'react'
import { Text, View } from 'react-native'

import { ChatBubbleIcon } from '@/ui/icons/ChatBubbleIcon'
import { ExpandIcon } from '@/ui/icons/ExpandIcon'
import { InfoIcon } from '@/ui/icons/InfoIcon'
import { SparklesIcon } from '@/ui/icons/SparklesIcon'
import type { IconProps } from '@/ui/icons/types'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles } from '@/ui/theme'

import type { FeedUnit } from './feedModel'
import { feedColors, feedTextShadow } from './feedStyle'

interface FeedRailProps {
    unit: FeedUnit
    speed: number
    onUnit: () => void
    onSpeed: () => void
    onChat: () => void
    onInfo: () => void
}

export function speedLabel(speed: number): string {
    return `${speed}×`
}

export function FeedRail({ unit, speed, onUnit, onSpeed, onChat, onInfo }: FeedRailProps): ReactElement {
    const styles = useStyles()
    return (
        <View style={styles.rail} pointerEvents="box-none">
            {unit === 'moment' ? (
                <RailButton label="Session" Icon={ExpandIcon} onPress={onUnit} testID="feed-unit" />
            ) : (
                <RailButton label="Moments" Icon={SparklesIcon} onPress={onUnit} testID="feed-unit" />
            )}
            <RailButton label="Speed" onPress={onSpeed} testID="feed-speed">
                <Text style={styles.speed}>{speedLabel(speed)}</Text>
            </RailButton>
            <RailButton label="Chat" Icon={ChatBubbleIcon} onPress={onChat} testID="feed-chat" />
            <RailButton label="Info" Icon={InfoIcon} onPress={onInfo} testID="feed-info" />
        </View>
    )
}

interface RailButtonProps {
    label: string
    Icon?: ComponentType<IconProps>
    children?: ReactNode
    onPress: () => void
    testID: string
}

function RailButton({ label, Icon, children, onPress, testID }: RailButtonProps): ReactElement {
    const styles = useStyles()
    return (
        <Pressable44
            onPress={onPress}
            accessibilityLabel={label}
            style={styles.button}
            pressedStyle={styles.pressed}
            haptic="selection"
            testID={testID}
        >
            {({ pressed }) => (
                <>
                    <View style={[styles.circle, pressed && styles.circlePressed]}>
                        {Icon ? <Icon size={22} color={feedColors.text} /> : children}
                    </View>
                    <Text style={styles.label}>{label}</Text>
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
        width: 64,
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
    circlePressed: {
        backgroundColor: feedColors.glassPressed,
    },
    label: {
        fontSize: 12,
        fontWeight: '600',
        color: feedColors.text,
        ...feedTextShadow,
    },
    speed: {
        fontSize: 15,
        fontWeight: '700',
        color: feedColors.text,
    },
}))
