import type { ReactElement } from 'react'
import { StyleSheet, Text, View } from 'react-native'

import { ChevronRightIcon } from '@/ui/icons/ChevronRightIcon'
import { DashboardIcon } from '@/ui/icons/DashboardIcon'
import { ExternalLinkIcon } from '@/ui/icons/ExternalLinkIcon'
import { GlobeIcon } from '@/ui/icons/GlobeIcon'
import { LineChartIcon } from '@/ui/icons/LineChartIcon'
import { RecordingIcon } from '@/ui/icons/RecordingIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { colors, radii, type } from '@/ui/tokens'

import { GroupFrame, type GroupPosition } from './ViewRow'

export type BrowseEntry = 'dashboards' | 'insights' | 'web' | 'recordings'

const ENTRIES: Record<BrowseEntry, { label: string; web: boolean }> = {
    dashboards: { label: 'Dashboards', web: false },
    insights: { label: 'Insights', web: false },
    web: { label: 'Web analytics', web: false },
    recordings: { label: 'Recordings', web: true },
}

export const BROWSE_ENTRIES: readonly BrowseEntry[] = ['dashboards', 'insights', 'web', 'recordings']

export function browseEntryLabel(entry: BrowseEntry): string {
    return ENTRIES[entry].label
}

function EntryIcon({ entry }: { entry: BrowseEntry }): ReactElement {
    switch (entry) {
        case 'dashboards':
            return <DashboardIcon size={17} color={colors.muted} />
        case 'insights':
            return <LineChartIcon size={17} color={colors.muted} />
        case 'web':
            return <GlobeIcon size={17} color={colors.muted} />
        case 'recordings':
            return <RecordingIcon size={17} color={colors.muted} />
    }
}

interface BrowseEntryRowProps {
    entry: BrowseEntry
    position: GroupPosition
    /** False dims a row that cannot open, such as Recordings in the demo. */
    enabled: boolean
    onPress: (entry: BrowseEntry) => void
}

export function BrowseEntryRow({ entry, position, enabled, onPress }: BrowseEntryRowProps): ReactElement {
    const { label, web } = ENTRIES[entry]
    return (
        <GroupFrame position={position}>
            <Pressable44
                onPress={() => onPress(entry)}
                disabled={!enabled}
                accessibilityLabel={web ? `${label}, opens on the web` : label}
                accessibilityState={{ disabled: !enabled }}
                pressedBackground={colors.sunken}
                style={[styles.row, position !== 'first' && position !== 'only' && styles.divider]}
                testID={`views-browse-${entry}`}
            >
                <View style={styles.iconTile}>
                    <EntryIcon entry={entry} />
                </View>
                <Text style={[styles.label, !enabled && styles.disabled]}>{label}</Text>
                {web ? (
                    <ExternalLinkIcon size={16} color={enabled ? colors.tertiary : colors.disabled} />
                ) : (
                    <ChevronRightIcon size={13} color={colors.tertiary} />
                )}
            </Pressable44>
        </GroupFrame>
    )
}

const styles = StyleSheet.create({
    row: {
        height: 52,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        paddingHorizontal: 12,
    },
    divider: {
        borderTopWidth: 1,
        borderTopColor: colors.rowDivider,
    },
    iconTile: {
        width: 32,
        height: 32,
        borderRadius: radii.markLarge,
        backgroundColor: colors.sunken,
        alignItems: 'center',
        justifyContent: 'center',
    },
    label: {
        ...type.bodySmallStrong,
        flex: 1,
        color: colors.ink,
    },
    disabled: {
        color: colors.tertiary,
    },
})
