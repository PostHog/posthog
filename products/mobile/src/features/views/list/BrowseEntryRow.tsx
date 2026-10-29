import type { ReactElement } from 'react'
import { Text, View } from 'react-native'

import type { RowAnchor } from '@/features/inbox/contextMenuPlacement'
import type { NavPin } from '@/features/tabs/navPinStore'
import { ChevronRightIcon } from '@/ui/icons/ChevronRightIcon'
import { DashboardIcon } from '@/ui/icons/DashboardIcon'
import { ErrorTriangleIcon } from '@/ui/icons/ErrorTriangleIcon'
import { GlobeIcon } from '@/ui/icons/GlobeIcon'
import { LineChartIcon } from '@/ui/icons/LineChartIcon'
import { RecordingIcon } from '@/ui/icons/RecordingIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

import { useMenuTrigger } from './useMenuTrigger'
import { GroupFrame, type GroupPosition } from './ViewRow'

export type BrowseEntry = 'dashboards' | 'insights' | 'web' | 'replay' | 'errors'

const LABELS: Record<BrowseEntry, string> = {
    dashboards: 'Dashboards',
    insights: 'Insights',
    web: 'Web analytics',
    replay: 'Sessions',
    errors: 'Errors',
}

export const BROWSE_ENTRIES: readonly BrowseEntry[] = ['dashboards', 'insights', 'web', 'replay', 'errors']

export function browseEntryLabel(entry: BrowseEntry): string {
    return LABELS[entry]
}

export function browseEntryPin(entry: BrowseEntry): NavPin | null {
    return entry === 'errors' || entry === 'replay' ? entry : null
}

function EntryIcon({ entry }: { entry: BrowseEntry }): ReactElement {
    const colors = useColors()
    switch (entry) {
        case 'dashboards':
            return <DashboardIcon size={17} color={colors.muted} />
        case 'insights':
            return <LineChartIcon size={17} color={colors.muted} />
        case 'web':
            return <GlobeIcon size={17} color={colors.muted} />
        case 'replay':
            return <RecordingIcon size={17} color={colors.muted} />
        case 'errors':
            return <ErrorTriangleIcon size={17} color={colors.muted} />
    }
}

interface BrowseEntryRowProps {
    entry: BrowseEntry
    position: GroupPosition
    /** False dims a row that cannot open, such as Sessions and Errors in the demo. */
    enabled: boolean
    onPress: (entry: BrowseEntry) => void
    onMenu: (entry: BrowseEntry, anchor: RowAnchor) => void
}

export function BrowseEntryRow({ entry, position, enabled, onPress, onMenu }: BrowseEntryRowProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const menu = useMenuTrigger(entry, onMenu)
    const label = LABELS[entry]
    const pinnable = enabled && browseEntryPin(entry) !== null
    return (
        <GroupFrame position={position}>
            <View ref={menu.ref}>
                <Pressable44
                    onPress={() => onPress(entry)}
                    onLongPress={pinnable ? menu.onLongPress : undefined}
                    accessibilityActions={pinnable ? menu.accessibilityActions : undefined}
                    onAccessibilityAction={pinnable ? menu.onAccessibilityAction : undefined}
                    disabled={!enabled}
                    accessibilityLabel={label}
                    accessibilityState={{ disabled: !enabled }}
                    pressedBackground={colors.sunken}
                    style={[styles.row, position !== 'first' && position !== 'only' && styles.divider]}
                    testID={`views-browse-${entry}`}
                >
                    <View style={styles.iconTile}>
                        <EntryIcon entry={entry} />
                    </View>
                    <Text style={[styles.label, !enabled && styles.disabled]}>{label}</Text>
                    <ChevronRightIcon size={13} color={enabled ? colors.tertiary : colors.disabled} />
                </Pressable44>
            </View>
        </GroupFrame>
    )
}

const useStyles = createStyles(({ colors }) => ({
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
}))
