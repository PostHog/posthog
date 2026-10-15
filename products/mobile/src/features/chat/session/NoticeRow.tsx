import { memo, type ReactElement } from 'react'
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native'

import { CheckIcon } from '@/ui/icons/CheckIcon'
import { WarningIcon } from '@/ui/icons/WarningIcon'
import { colors, iconSizes, type } from '@/ui/tokens'

import type { SessionNoticeItem } from './types'

interface NoticeRowProps {
    item: SessionNoticeItem
}

function NoticeIcon({ item }: NoticeRowProps): ReactElement | null {
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
    return (
        <View style={styles.row} accessibilityRole="text" testID={`session-notice-${item.id}`}>
            <NoticeIcon item={item} />
            <Text style={styles.text}>{item.text}</Text>
        </View>
    )
})

const styles = StyleSheet.create({
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
})
