import type { ReactElement } from 'react'
import { Text, View } from 'react-native'

import { groupThousands } from '@/model/adapters/text'
import type { LiveBreakdown, LiveBreakdownKind } from '@/model/live'
import { seriesColor } from '@/ui/chart/palette'
import { SegmentedPill } from '@/ui/SegmentedPill'
import { createStyles, useTheme } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

import { LiveCard, LiveCardNote, NOT_LOADED_TEXT } from './LiveCard'

const TABS: readonly { key: LiveBreakdownKind; label: string; empty: string }[] = [
    { key: 'devices', label: 'Devices', empty: 'No device data' },
    { key: 'browsers', label: 'Browsers', empty: 'No browser data' },
    { key: 'countries', label: 'Countries', empty: 'No country data' },
]

interface LiveBreakdownCardProps {
    kind: LiveBreakdownKind
    breakdown: LiveBreakdown | null
    onChange: (kind: LiveBreakdownKind) => void
}

/** The web's Devices, Browsers and Countries cards as one card with a switch, to keep the screen short. */
export function LiveBreakdownCard({ kind, breakdown, onChange }: LiveBreakdownCardProps): ReactElement {
    const { colors, chartPalette } = useTheme()
    const styles = useStyles()
    const tab = TABS.find((entry) => entry.key === kind) ?? TABS[0]
    let body: ReactElement
    if (!breakdown) {
        body = <LiveCardNote text={NOT_LOADED_TEXT} testID="live-breakdown-not-loaded" />
    } else if (breakdown.rows.length === 0) {
        body = <LiveCardNote text={tab?.empty ?? ''} testID="live-breakdown-empty" />
    } else {
        body = (
            <View style={styles.body}>
                <View style={styles.total}>
                    <Text style={styles.totalValue} testID="live-breakdown-total">
                        {groupThousands(breakdown.total)}
                    </Text>
                    <Text style={styles.totalLabel}>{breakdown.statLabel}</Text>
                </View>
                {breakdown.rows.map((row, index) => {
                    const percent = `${row.percent.toFixed(0)}%`
                    return (
                        <View
                            key={row.key}
                            style={styles.row}
                            accessible
                            accessibilityLabel={`${row.label}, ${percent}, ${groupThousands(row.count)} ${breakdown.statLabel}`}
                            testID={`live-breakdown-row-${index}`}
                        >
                            <Text style={[styles.label, index === 0 && styles.top]} numberOfLines={1}>
                                {row.flag ? `${row.flag}  ` : ''}
                                {row.label}
                            </Text>
                            <View style={styles.track}>
                                <View
                                    style={[
                                        styles.fill,
                                        {
                                            width: `${Math.max(1, row.percent)}%`,
                                            backgroundColor: seriesColor(index, chartPalette),
                                        },
                                    ]}
                                />
                            </View>
                            <Text style={[styles.percent, index === 0 && styles.top]}>{percent}</Text>
                        </View>
                    )
                })}
            </View>
        )
    }
    return (
        <LiveCard testID="live-breakdown">
            <SegmentedPill
                height={40}
                segments={TABS.map((entry) => ({
                    key: entry.key,
                    accessibilityLabel: entry.label,
                    accessibilityRole: 'tab',
                    selected: entry.key === kind,
                    onPress: () => {
                        if (entry.key !== kind) {
                            onChange(entry.key)
                        }
                    },
                    testID: `live-breakdown-${entry.key}`,
                    children: (
                        <Text style={[styles.segment, entry.key === kind && { color: colors.ink }]}>{entry.label}</Text>
                    ),
                }))}
            />
            {body}
        </LiveCard>
    )
}

const useStyles = createStyles(({ colors }) => ({
    body: {
        gap: 10,
    },
    total: {
        alignItems: 'center',
        paddingVertical: 6,
    },
    totalValue: {
        fontSize: 32,
        lineHeight: 38,
        fontWeight: '700',
        color: colors.ink,
        fontVariant: ['tabular-nums'],
    },
    totalLabel: {
        ...type.meta,
        color: colors.tertiary,
    },
    row: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 10,
        minHeight: 28,
    },
    label: {
        ...type.metaSmall,
        width: '38%',
        color: colors.secondary,
    },
    top: {
        color: colors.ink,
        fontWeight: '600',
    },
    track: {
        flex: 1,
        height: 8,
        borderRadius: radii.pill,
        backgroundColor: colors.sunken,
        overflow: 'hidden',
    },
    fill: {
        height: '100%',
        borderRadius: radii.pill,
    },
    percent: {
        ...type.metaSmall,
        width: 44,
        textAlign: 'right',
        color: colors.secondary,
        fontVariant: ['tabular-nums'],
    },
    segment: {
        ...type.buttonSmall,
        fontWeight: '500',
        color: colors.secondary,
    },
}))
