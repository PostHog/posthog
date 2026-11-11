import type { ReactElement } from 'react'
import { Text, View } from 'react-native'

import { WarningIcon } from '@/ui/icons/WarningIcon'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

import type { StatusLine } from '../freshness'

/**
 * Shown over cached values when the last read failed, offline or not: the phone cannot tell the two apart. The
 * status line keeps the age of the values, and the values dim.
 */
export function RefreshFailedBanner({ status }: { status: StatusLine }): ReactElement | null {
    const colors = useColors()
    const styles = useStyles()
    if (status.kind !== 'age' || !status.failed) {
        return null
    }
    return (
        <View style={styles.banner} accessibilityRole="alert" testID="view-refresh-failed">
            <WarningIcon size={20} color={colors.orange} />
            <Text style={styles.text}>
                Couldn't refresh, so these values may be out of date. Check your connection, then pull down to try
                again.
            </Text>
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    banner: {
        flexDirection: 'row',
        alignItems: 'flex-start',
        gap: 10,
        padding: 12,
        marginBottom: 12,
        borderRadius: radii.option,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
    },
    text: {
        ...type.metaSmall,
        lineHeight: 20,
        color: colors.ink,
        flex: 1,
    },
}))
