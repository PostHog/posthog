import { Fragment, type ReactElement } from 'react'
import { StyleSheet, Text, View } from 'react-native'

import { ChatBubbleIcon } from '@/ui/icons/ChatBubbleIcon'
import { ClockIcon } from '@/ui/icons/ClockIcon'
import { ReassignIcon } from '@/ui/icons/ReassignIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { colors, iconSizes, radii, shadows, type } from '@/ui/tokens'

interface ActionPillProps {
    onReassign: () => void
    onSnooze: () => void
    onChat: () => void
}

export function ActionPill({ onReassign, onSnooze, onChat }: ActionPillProps): ReactElement {
    const buttons = [
        { key: 'reassign', label: 'Reassign', Icon: ReassignIcon, onPress: onReassign },
        { key: 'snooze', label: 'Snooze', Icon: ClockIcon, onPress: onSnooze },
        { key: 'chat', label: 'Chat', Icon: ChatBubbleIcon, onPress: onChat },
    ]
    return (
        <View style={[styles.outer, shadows.actionPill]}>
            <View style={styles.inner}>
                {buttons.map(({ key, label, Icon, onPress }, index) => (
                    <Fragment key={key}>
                        {index > 0 ? <View style={styles.divider} /> : null}
                        <Pressable44
                            onPress={onPress}
                            pressedBackground={colors.background}
                            style={styles.button}
                            testID={`action-${key}`}
                        >
                            <Icon size={iconSizes.control} />
                            <Text style={styles.label} numberOfLines={1}>
                                {label}
                            </Text>
                        </Pressable44>
                    </Fragment>
                ))}
            </View>
        </View>
    )
}

const styles = StyleSheet.create({
    // 52pt buttons inside a 1pt border.
    outer: {
        height: 54,
        borderRadius: radii.pill,
        backgroundColor: colors.white,
        borderWidth: 1,
        borderColor: colors.hairline,
    },
    inner: {
        flex: 1,
        flexDirection: 'row',
        borderRadius: radii.pill,
        overflow: 'hidden',
    },
    button: {
        flex: 1,
        minWidth: 0,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 4,
    },
    label: {
        ...type.metaSmall,
        fontWeight: '600',
        color: colors.ink,
    },
    divider: {
        width: 1,
        marginVertical: 14,
        backgroundColor: colors.hairline,
    },
})
