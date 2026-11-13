import type { ReactElement } from 'react'
import { Text, View } from 'react-native'

import { groupThousands, plural } from '@/model/adapters/text'
import type { LiveBreakdownRow } from '@/model/live'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

import { LiveCard } from './LiveCard'
import { LIVE_ROW_HEIGHT, LiveSlidingRow } from './LiveSlidingRow'

interface LiveCountryListProps {
    /** Most visitors first, as `liveWorld` sorts them. */
    countries: LiveBreakdownRow[]
    selected: string | null
    onSelect: (code: string) => void
    /** The first row's top, from the top of the card, so the screen can scroll a row into view. */
    onRowsLayout: (y: number) => void
}

/** Every country with its visitors and a share bar scaled to the leading country. Rows slide when ranks change. */
export function LiveCountryList({ countries, selected, onSelect, onRowsLayout }: LiveCountryListProps): ReactElement {
    const styles = useStyles()
    const most = countries[0]?.count ?? 0
    return (
        <LiveCard flush testID="live-countries-list">
            <View style={styles.header}>
                <Text style={styles.columnLabel}>Country</Text>
                <Text style={styles.columnLabel}>Visitors</Text>
            </View>
            <View
                style={{ height: countries.length * LIVE_ROW_HEIGHT }}
                onLayout={(event) => onRowsLayout(event.nativeEvent.layout.y)}
            >
                {countries.map((country, index) => (
                    <CountryRow
                        key={country.key}
                        country={country}
                        index={index}
                        share={most > 0 ? country.count / most : 0}
                        selected={country.key === selected}
                        onSelect={onSelect}
                    />
                ))}
            </View>
        </LiveCard>
    )
}

interface CountryRowProps {
    country: LiveBreakdownRow
    index: number
    /** Visitors over the leading country's, 0 to 1. */
    share: number
    selected: boolean
    onSelect: (code: string) => void
}

function CountryRow({ country, index, share, selected, onSelect }: CountryRowProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const percent = `${country.percent.toFixed(1)}%`
    return (
        <LiveSlidingRow index={index}>
            <Pressable44
                onPress={() => onSelect(country.key)}
                accessibilityState={{ selected }}
                accessibilityLabel={`${country.label}, ${plural(country.count, 'visitor')}, ${percent}`}
                pressedBackground={colors.pressed}
                hitSlop={0}
                style={[styles.row, selected && styles.selectedRow]}
                testID={`live-countries-row-${country.key}`}
            >
                <Text style={styles.flag}>{country.flag ?? ''}</Text>
                <Text style={[styles.name, selected && styles.selectedName]} numberOfLines={1}>
                    {country.label}
                </Text>
                <View style={styles.track}>
                    <View style={[styles.fill, { width: `${Math.max(4, share * 100)}%` }]} />
                </View>
                <Text style={styles.value} numberOfLines={1}>
                    {groupThousands(country.count)}
                    <Text style={styles.percent}> ({percent})</Text>
                </Text>
            </Pressable44>
        </LiveSlidingRow>
    )
}

const useStyles = createStyles(({ colors }) => ({
    header: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        marginHorizontal: 14,
        paddingBottom: 8,
        borderBottomWidth: 1,
        borderBottomColor: colors.rowDivider,
    },
    columnLabel: {
        ...type.eyebrow,
        textTransform: 'uppercase',
        color: colors.tertiary,
    },
    row: {
        flex: 1,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 10,
        paddingHorizontal: 14,
        borderBottomWidth: 1,
        borderBottomColor: colors.rowDivider,
    },
    selectedRow: {
        backgroundColor: colors.blueHighlight,
    },
    flag: {
        ...type.metaSmall,
        width: 20,
    },
    name: {
        ...type.metaSmall,
        flex: 1,
        color: colors.ink,
    },
    selectedName: {
        fontWeight: '600',
    },
    track: {
        width: 56,
        height: 8,
        borderRadius: radii.pill,
        backgroundColor: colors.sunken,
        overflow: 'hidden',
    },
    fill: {
        height: '100%',
        borderRadius: radii.pill,
        backgroundColor: colors.blue,
    },
    value: {
        ...type.bodySmallStrong,
        minWidth: 84,
        textAlign: 'right',
        color: colors.ink,
        fontVariant: ['tabular-nums'],
    },
    percent: {
        ...type.meta,
        fontWeight: '400',
        color: colors.tertiary,
    },
}))
