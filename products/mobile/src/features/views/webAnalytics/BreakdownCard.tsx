import type { ReactElement } from 'react'
import { Text } from 'react-native'

import { BREAKDOWN_LABELS, breakdownFilters } from '@/model/adapters/webAnalyticsBreakdowns'
import type { WebBreakdownRow, WebBreakdownSnapshot, WebFilter } from '@/model/views'
import { ChevronDownIcon } from '@/ui/icons/ChevronDownIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

import { BreakdownColumns, BreakdownRows } from './BreakdownRows'
import { CARD_ROWS, useWebItemData, type WebTileState } from './hooks'
import { WebCard, webCardState } from './WebCard'

interface BreakdownCardProps {
    tile: WebTileState
    filters: readonly WebFilter[]
    onOpenTabs: () => void
    onPressRow: (row: WebBreakdownRow) => void
    onOpenList: () => void
}

export function rowIsActive(filters: readonly WebFilter[], row: WebBreakdownRow): boolean {
    const filter = row.filter
    return Boolean(
        filter &&
            filters.some(
                (active) =>
                    active.id === filter.id && JSON.stringify(active.properties) === JSON.stringify(filter.properties)
            )
    )
}

export function BreakdownCard({ tile, filters, onOpenTabs, onPressRow, onOpenList }: BreakdownCardProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const item = useWebItemData<WebBreakdownSnapshot>(tile.data)
    const snapshot = item.snapshot
    const rows = snapshot?.rows ?? []
    const shown = rows.slice(0, CARD_ROWS)
    const more = rows.length - shown.length
    const tabLabel = BREAKDOWN_LABELS[tile.breakdown]
    const testID = `web-tile-${tile.def.id}`
    const title = (
        <Pressable44
            onPress={onOpenTabs}
            hitSlop={{ top: 10, bottom: 10, left: 6, right: 6 }}
            accessibilityLabel={`${tile.def.title}, ${tabLabel}`}
            accessibilityHint="Changes how this list breaks down the visitors."
            style={styles.titleButton}
            testID={`${testID}-tabs`}
        >
            <Text style={styles.title} numberOfLines={1}>
                {tabLabel}
            </Text>
            <ChevronDownIcon size={12} color={colors.secondary} />
        </Pressable44>
    )
    return (
        <WebCard
            title={title}
            accessory={
                snapshot && rows.length > 0 ? <BreakdownColumns secondaryLabel={snapshot.secondaryLabel} /> : null
            }
            state={webCardState(item, rows.length > 0)}
            error={item.error}
            stale={snapshot?.refreshFailed ?? false}
            updating={item.updating}
            loadingHeight={CARD_ROWS * 44}
            testID={testID}
        >
            <BreakdownRows
                rows={shown}
                secondaryLabel={snapshot?.secondaryLabel ?? null}
                isActive={(row) => rowIsActive(filters, row)}
                onPressRow={onPressRow}
                testID={testID}
            />
            {more > 0 || snapshot?.hasMore ? (
                <Pressable44
                    onPress={onOpenList}
                    hitSlop={0}
                    pressedBackground={colors.sunken}
                    accessibilityLabel={`Show all ${tile.def.title.toLowerCase()} by ${tabLabel.toLowerCase()}`}
                    style={styles.more}
                    testID={`${testID}-more`}
                >
                    <Text style={styles.moreText}>{snapshot?.hasMore ? 'Show all' : `+${more} more`}</Text>
                </Pressable44>
            ) : null}
            {breakdownFilters(tile.breakdown) ? null : (
                <Text style={styles.caption}>Outbound clicks can't be used as a filter.</Text>
            )}
        </WebCard>
    )
}

const useStyles = createStyles(({ colors }) => ({
    titleButton: {
        alignSelf: 'flex-start',
        maxWidth: '100%',
        flexDirection: 'row',
        alignItems: 'center',
        gap: 6,
        minHeight: 24,
    },
    title: {
        flexShrink: 1,
        fontSize: 15,
        lineHeight: 20,
        fontWeight: '600',
        color: colors.ink,
    },
    more: {
        minHeight: 40,
        justifyContent: 'center',
        paddingHorizontal: 6,
        marginHorizontal: -6,
        marginTop: 4,
        borderRadius: radii.markLarge,
    },
    moreText: {
        ...type.meta,
        fontWeight: '600',
        color: colors.secondary,
    },
    caption: {
        ...type.meta,
        marginTop: 8,
        color: colors.tertiary,
    },
}))
