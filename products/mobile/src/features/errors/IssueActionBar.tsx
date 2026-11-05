import { Fragment, type ReactElement } from 'react'
import { ActivityIndicator, Text, View } from 'react-native'

import { CheckCircleIcon } from '@/ui/icons/CheckCircleIcon'
import { ComposeIcon } from '@/ui/icons/ComposeIcon'
import { EyeOffIcon } from '@/ui/icons/EyeOffIcon'
import { RefreshIcon } from '@/ui/icons/RefreshIcon'
import type { IconProps } from '@/ui/icons/types'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useTheme } from '@/ui/theme'
import { iconSizes, layout, radii, type } from '@/ui/tokens'
import { bottomOffset, useScreenInsets } from '@/ui/useScreenInsets'

interface IssueActionBarProps {
    active: boolean
    pending: boolean
    onResolve: () => void
    onSuppress: () => void
    onReopen: () => void
    onChat: () => void
}

interface PillButton {
    key: string
    label: string
    Icon: (props: IconProps) => ReactElement
    onPress: () => void
}

export function IssueActionBar({
    active,
    pending,
    onResolve,
    onSuppress,
    onReopen,
    onChat,
}: IssueActionBarProps): ReactElement {
    const { colors, shadows } = useTheme()
    const styles = useStyles()
    const insets = useScreenInsets()
    const buttons: PillButton[] = active
        ? [
              { key: 'resolve', label: 'Resolve', Icon: CheckCircleIcon, onPress: onResolve },
              { key: 'suppress', label: 'Suppress', Icon: EyeOffIcon, onPress: onSuppress },
          ]
        : [{ key: 'reopen', label: 'Reopen', Icon: RefreshIcon, onPress: onReopen }]
    return (
        <View style={[styles.bar, { paddingBottom: bottomOffset(insets, 38) }]} testID="issue-action-bar">
            <View style={[styles.pill, shadows.actionPill]}>
                <View style={styles.inner}>
                    {buttons.map(({ key, label, Icon, onPress }, index) => (
                        <Fragment key={key}>
                            {index > 0 ? <View style={styles.divider} /> : null}
                            <Pressable44
                                onPress={onPress}
                                disabled={pending}
                                accessibilityRole="button"
                                accessibilityLabel={label}
                                accessibilityState={{ disabled: pending, busy: pending }}
                                pressedBackground={colors.background}
                                style={styles.button}
                                testID={`issue-${key}`}
                            >
                                {pending ? (
                                    <ActivityIndicator size="small" color={colors.muted} />
                                ) : (
                                    <Icon size={iconSizes.control} />
                                )}
                                <Text style={[styles.label, pending && styles.labelPending]} numberOfLines={1}>
                                    {label}
                                </Text>
                            </Pressable44>
                        </Fragment>
                    ))}
                </View>
            </View>
            <Pressable44
                onPress={onChat}
                accessibilityRole="button"
                accessibilityLabel="Chat about this issue"
                pressedBackground={colors.inkHover}
                style={[styles.chat, shadows.fab]}
                haptic="selection"
                testID="issue-chat"
            >
                <ComposeIcon size={iconSizes.navigation} color={colors.onInk} />
            </Pressable44>
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    bar: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 10,
        backgroundColor: colors.background,
        paddingTop: 10,
        paddingHorizontal: layout.actionBarGutter,
        borderTopWidth: 1,
        borderTopColor: colors.footerHairline,
    },
    // 52pt buttons inside a 1pt border, the same as the report's action pill.
    pill: {
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
        gap: 6,
    },
    label: {
        ...type.bodySmallStrong,
        color: colors.ink,
    },
    labelPending: {
        color: colors.muted,
    },
    divider: {
        width: 1,
        marginVertical: 14,
        backgroundColor: colors.hairline,
    },
    chat: {
        width: 54,
        height: 54,
        borderRadius: radii.pill,
        backgroundColor: colors.ink,
        alignItems: 'center',
        justifyContent: 'center',
    },
}))
