import { Fragment, type ReactElement } from 'react'
import { Text, View } from 'react-native'

import { ErrorTriangleIcon } from '@/ui/icons/ErrorTriangleIcon'
import { InfoIcon } from '@/ui/icons/InfoIcon'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

import type { HealthItem } from './detailModel'

/** Health findings, most severe first, one per row. Shown only when there are some. */
export function HealthCard({ items }: { items: readonly HealthItem[] }): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    return (
        <View style={styles.card} testID="experiment-health">
            {items.map((item, index) => {
                const warn = item.severity !== 'info'
                return (
                    <Fragment key={item.key}>
                        {index > 0 ? <View style={styles.divider} /> : null}
                        <View
                            style={styles.row}
                            accessible
                            accessibilityLabel={`${warn ? 'Warning' : 'Note'}: ${item.title}. ${item.detail}`}
                        >
                            <View style={[styles.icon, warn ? styles.iconWarn : styles.iconInfo]}>
                                {warn ? (
                                    <ErrorTriangleIcon size={14} color={colors.orange} strokeWidth={2.4} />
                                ) : (
                                    <InfoIcon size={14} color={colors.blue} strokeWidth={2.4} />
                                )}
                            </View>
                            <View style={styles.body}>
                                <Text style={styles.title}>{item.title}</Text>
                                {item.detail ? (
                                    <Text style={styles.detail} numberOfLines={6}>
                                        {item.detail}
                                    </Text>
                                ) : null}
                            </View>
                        </View>
                    </Fragment>
                )
            })}
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    card: {
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
        overflow: 'hidden',
    },
    row: {
        flexDirection: 'row',
        alignItems: 'flex-start',
        gap: 12,
        padding: 14,
    },
    icon: {
        width: 26,
        height: 26,
        borderRadius: 13,
        alignItems: 'center',
        justifyContent: 'center',
    },
    iconWarn: {
        backgroundColor: colors.sunken,
    },
    iconInfo: {
        backgroundColor: colors.blueHighlight,
    },
    body: {
        flex: 1,
        gap: 2,
    },
    title: {
        ...type.bodySmallStrong,
        color: colors.ink,
    },
    detail: {
        ...type.meta,
        color: colors.secondary,
    },
    divider: {
        height: 1,
        backgroundColor: colors.hairline,
    },
}))
