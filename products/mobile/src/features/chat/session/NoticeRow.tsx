import { memo, type ReactElement } from 'react'
import { ActivityIndicator, Text, View } from 'react-native'

import { CheckIcon } from '@/ui/icons/CheckIcon'
import { WarningIcon } from '@/ui/icons/WarningIcon'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, type } from '@/ui/tokens'

import type { SessionNoticeItem } from './types'

interface NoticeRowProps {
    item: SessionNoticeItem
}

function NoticeIcon({ item }: NoticeRowProps): ReactElement | null {
    const colors = useColors()
    if (item.spinning) {
        return <ActivityIndicator size="small" color={colors.tertiary} />
    }
    if (item.tone === 'completed') {
        return <CheckIcon size={iconSizes.inline} color={colors.muted} />
    }
    if (item.tone === 'failed') {
        return <WarningIcon size={iconSizes.inline} color={colors.orange} />
    }
    return null
}

export const NoticeRow = memo(function NoticeRow({ item }: NoticeRowProps): ReactElement {
    const styles = useStyles()
    return (
        <View style={styles.row} accessibilityRole="text" testID={`session-notice-${item.id}`}>
            <NoticeIcon item={item} />
            <Text style={styles.text}>{item.text}</Text>
        </View>
    )
})

const useStyles = createStyles(({ colors }) => ({
    row: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 6,
        paddingHorizontal: 12,
    },
    text: {
        ...type.meta,
        color: colors.muted,
        textAlign: 'center',
        flexShrink: 1,
    },
}))
