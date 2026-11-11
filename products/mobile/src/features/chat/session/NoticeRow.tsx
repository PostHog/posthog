import { memo, type ReactElement, useState } from 'react'
import { ActivityIndicator, Text, View } from 'react-native'

import { CheckIcon } from '@/ui/icons/CheckIcon'
import { WarningIcon } from '@/ui/icons/WarningIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, type } from '@/ui/tokens'

import type { SessionNoticeItem } from './types'

interface NoticeRowProps {
    item: SessionNoticeItem
    onToggle?: () => void
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

export const NoticeRow = memo(function NoticeRow({ item, onToggle }: NoticeRowProps): ReactElement {
    const styles = useStyles()
    const [expanded, setExpanded] = useState(false)
    const [overflows, setOverflows] = useState(false)

    return (
        <View style={styles.row} testID={`session-notice-${item.id}`}>
            <NoticeIcon item={item} />
            <View style={styles.body}>
                <Text style={styles.text} numberOfLines={expanded ? undefined : 2} ellipsizeMode="tail">
                    {item.text}
                </Text>
                {/* Measure without a line limit so truncation cannot hide overflow from the toggle. */}
                <Text
                    style={[styles.text, styles.measure]}
                    accessible={false}
                    accessibilityElementsHidden
                    importantForAccessibility="no-hide-descendants"
                    pointerEvents="none"
                    onTextLayout={({ nativeEvent }) => {
                        const nextOverflows = nativeEvent.lines.length > 2
                        setOverflows(nextOverflows)
                        if (!nextOverflows) {
                            setExpanded(false)
                        }
                    }}
                    testID={`session-notice-measure-${item.id}`}
                >
                    {item.text}
                </Text>
                {overflows ? (
                    <Pressable44
                        onPress={() => {
                            onToggle?.()
                            setExpanded(!expanded)
                        }}
                        accessibilityState={{ expanded }}
                        style={styles.toggle}
                    >
                        <Text style={styles.toggleText}>{expanded ? 'Show less' : 'Show more'}</Text>
                    </Pressable44>
                ) : null}
            </View>
        </View>
    )
})

const useStyles = createStyles(({ colors }) => ({
    row: {
        flexDirection: 'row',
        alignItems: 'flex-start',
        gap: 6,
    },
    body: {
        flex: 1,
        minWidth: 0,
    },
    text: {
        ...type.meta,
        color: colors.muted,
        textAlign: 'left',
    },
    measure: {
        position: 'absolute',
        top: 0,
        left: 0,
        right: 0,
        opacity: 0,
    },
    toggle: {
        alignSelf: 'flex-start',
        minHeight: 32,
        justifyContent: 'center',
    },
    toggleText: {
        ...type.meta,
        color: colors.blue,
    },
}))
