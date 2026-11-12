import { Fragment, type ReactElement } from 'react'
import { Text, View } from 'react-native'

import { CheckCircleIcon } from '@/ui/icons/CheckCircleIcon'
import { EyeOffIcon } from '@/ui/icons/EyeOffIcon'
import { ReassignIcon } from '@/ui/icons/ReassignIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useTheme } from '@/ui/theme'
import { iconSizes, radii, type } from '@/ui/tokens'

interface ActionPillProps {
    onReassign: () => void
    onResolve: () => void
    onDismiss: () => void
}

export function ActionPill({ onReassign, onResolve, onDismiss }: ActionPillProps): ReactElement {
    const { colors, shadows } = useTheme()
    const styles = useStyles()
    const buttons = [
        { key: 'reassign', label: 'Reassign', Icon: ReassignIcon, onPress: onReassign },
        { key: 'resolve', label: 'Resolve', Icon: CheckCircleIcon, onPress: onResolve },
        { key: 'dismiss', label: 'Dismiss', Icon: EyeOffIcon, onPress: onDismiss },
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

const useStyles = createStyles(({ colors }) => ({
    // 52pt buttons inside a 1pt border.
    outer: {
        flex: 1,
        height: 54,
        borderRadius: radii.pill,
        backgroundColor: colors.surface,
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
}))
