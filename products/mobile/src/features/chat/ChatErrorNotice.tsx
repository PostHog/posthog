import type { ReactElement, ReactNode } from 'react'
import { Text, View } from 'react-native'

import { CloseIcon } from '@/ui/icons/CloseIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, radii, type } from '@/ui/tokens'

interface ChatErrorNoticeProps {
    message: string
    onDismiss?: () => void
    actions?: ReactNode
    testID?: string
}

export function ChatErrorNotice({ message, onDismiss, actions, testID }: ChatErrorNoticeProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    return (
        <View style={styles.notice} testID={testID}>
            <View style={styles.row}>
                <Text style={styles.message} accessibilityRole="alert" accessibilityLiveRegion="polite">
                    {message}
                </Text>
                {onDismiss ? (
                    <Pressable44
                        onPress={onDismiss}
                        accessibilityLabel="Dismiss"
                        pressedBackground={colors.pressed}
                        hitSlop={0}
                        style={styles.dismiss}
                    >
                        <CloseIcon size={iconSizes.inline} color={colors.orange} />
                    </Pressable44>
                ) : null}
            </View>
            {actions ? <View style={styles.actions}>{actions}</View> : null}
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    notice: {
        paddingLeft: 12,
        paddingRight: 4,
        paddingVertical: 4,
        borderWidth: 1,
        borderColor: colors.border,
        borderRadius: radii.card,
        backgroundColor: colors.background,
    },
    row: {
        flexDirection: 'row',
        alignItems: 'flex-start',
        gap: 8,
    },
    message: {
        ...type.meta,
        color: colors.orange,
        flex: 1,
        minWidth: 0,
        paddingVertical: 8,
    },
    dismiss: {
        width: 44,
        height: 44,
        flexShrink: 0,
        alignItems: 'center',
        justifyContent: 'center',
        borderRadius: radii.card,
    },
    actions: {
        flexDirection: 'row',
        flexWrap: 'wrap',
        gap: 8,
        paddingRight: 8,
        paddingBottom: 4,
    },
}))
