import { type ReactElement, useEffect } from 'react'
import { Text, View } from 'react-native'

import type { InboxItem, ReportView } from '@/model/types'
import { Dot } from '@/ui/Dot'
import { CloseIcon } from '@/ui/icons/CloseIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useTheme } from '@/ui/theme'
import { iconSizes, radii } from '@/ui/tokens'

import { useReport } from '../report/hooks'

interface ContextChipProps {
    reportId: string
    item?: InboxItem
    onReport: (report: ReportView) => void
    onRemove: () => void
}

/** An attached report in the composer. Each chip loads its own report, so any number can be attached. */
export function ContextChip({ reportId, item, onReport, onRemove }: ContextChipProps): ReactElement {
    const { colors, accentColor } = useTheme()
    const styles = useStyles()
    const report = useReport(reportId)
    const data = report.data

    useEffect(() => {
        if (data) {
            onReport(data)
        }
    }, [data, onReport])

    const title = data?.title ?? item?.title ?? 'Loading report…'
    const accent = data?.accent ?? item?.accent ?? 'resolved'
    return (
        <View style={styles.chip} testID="chat-context-chip">
            <Dot color={accentColor[accent]} size={9} />
            <Text style={styles.title} numberOfLines={1}>
                {title}
            </Text>
            <Pressable44
                onPress={onRemove}
                accessibilityLabel={`Remove ${title}`}
                pressedBackground={colors.hairline}
                style={styles.remove}
                hitSlop={10}
            >
                <CloseIcon size={iconSizes.small} color={colors.muted} strokeWidth={2.6} />
            </Pressable44>
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    chip: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
        height: 36,
        paddingLeft: 10,
        paddingRight: 6,
        borderRadius: radii.pill,
        backgroundColor: colors.sunken,
        maxWidth: '100%',
    },
    title: {
        fontSize: 14,
        lineHeight: 19.6,
        fontWeight: '600',
        color: colors.ink,
        flexShrink: 1,
    },
    remove: {
        width: 24,
        height: 24,
        borderRadius: 12,
        alignItems: 'center',
        justifyContent: 'center',
    },
}))
