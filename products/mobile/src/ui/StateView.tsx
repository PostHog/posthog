import type { ReactElement, ReactNode } from 'react'
import { ActivityIndicator, Text, View } from 'react-native'

import { Pressable44 } from './Pressable44'
import { createStyles, useColors } from './theme'
import { radii, type } from './tokens'

interface StateViewProps {
    title: string
    message?: string
    icon?: ReactNode
    actionLabel?: string
    onAction?: () => void
    /** A quieter action under the first one, such as a fallback. */
    secondaryActionLabel?: string
    onSecondaryAction?: () => void
    testID?: string
}

export function StateView({
    title,
    message,
    icon,
    actionLabel,
    onAction,
    secondaryActionLabel,
    onSecondaryAction,
    testID,
}: StateViewProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    return (
        <View style={styles.container} testID={testID}>
            {icon}
            <Text style={styles.title}>{title}</Text>
            {message ? <Text style={styles.message}>{message}</Text> : null}
            {actionLabel && onAction ? (
                <Pressable44
                    onPress={onAction}
                    style={styles.action}
                    pressedBackground={colors.inkHover}
                    testID={testID ? `${testID}-action` : undefined}
                >
                    <Text style={styles.actionText}>{actionLabel}</Text>
                </Pressable44>
            ) : null}
            {secondaryActionLabel && onSecondaryAction ? (
                <Pressable44
                    onPress={onSecondaryAction}
                    style={styles.secondaryAction}
                    pressedBackground={colors.sunken}
                    testID={testID ? `${testID}-secondary-action` : undefined}
                >
                    <Text style={styles.secondaryActionText}>{secondaryActionLabel}</Text>
                </Pressable44>
            ) : null}
        </View>
    )
}

export function LoadingView({ label = 'Loading' }: { label?: string }): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    return (
        <View style={styles.container} accessibilityLabel={label} accessibilityRole="progressbar">
            <ActivityIndicator color={colors.ink} />
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    container: {
        flex: 1,
        alignItems: 'center',
        justifyContent: 'center',
        gap: 8,
        paddingHorizontal: 28,
        paddingVertical: 48,
    },
    title: {
        ...type.sheetTitleLarge,
        color: colors.ink,
        textAlign: 'center',
        marginTop: 6,
    },
    message: {
        ...type.bodySmall,
        color: colors.muted,
        textAlign: 'center',
    },
    action: {
        marginTop: 12,
        height: 44,
        paddingHorizontal: 20,
        borderRadius: radii.pill,
        backgroundColor: colors.ink,
        alignItems: 'center',
        justifyContent: 'center',
    },
    actionText: {
        ...type.buttonSmall,
        color: colors.onInk,
    },
    secondaryAction: {
        height: 44,
        paddingHorizontal: 20,
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.border,
        alignItems: 'center',
        justifyContent: 'center',
    },
    secondaryActionText: {
        ...type.buttonSmall,
        color: colors.ink,
    },
}))
