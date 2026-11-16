import { memo, type ReactElement, type ReactNode } from 'react'
import { Text, View, type ViewStyle } from 'react-native'

import type { RowAnchor } from '@/features/inbox/contextMenuPlacement'
import type { ViewRef } from '@/model/views'
import { PinIcon } from '@/ui/icons/PinIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

import { useMenuTrigger } from './useMenuTrigger'
import { ViewIcon } from './viewMeta'

export const VIEW_ROW_HEIGHT = 58

/** Where a row sits in its rounded group, so the group reads as one card. */
export type GroupPosition = 'only' | 'first' | 'middle' | 'last'

export function groupPosition(index: number, count: number): GroupPosition {
    if (count <= 1) {
        return 'only'
    }
    return index === 0 ? 'first' : index === count - 1 ? 'last' : 'middle'
}

const CORNERS: Record<GroupPosition, ViewStyle> = {
    only: { borderRadius: radii.option, borderTopWidth: 1, borderBottomWidth: 1 },
    first: { borderTopLeftRadius: radii.option, borderTopRightRadius: radii.option, borderTopWidth: 1 },
    middle: {},
    last: { borderBottomLeftRadius: radii.option, borderBottomRightRadius: radii.option, borderBottomWidth: 1 },
}

/** The white, bordered frame of one row in a group, with the divider above every row but the first. */
export function GroupFrame({ position, children }: { position: GroupPosition; children: ReactNode }): ReactElement {
    const styles = useStyles()
    return <View style={[styles.frame, CORNERS[position]]}>{children}</View>
}

interface ViewRowProps<T extends ViewRef> {
    view: T
    meta: string | null
    position: GroupPosition
    /** Null hides the pin button for views only the web can pin. */
    pinned: boolean | null
    onOpen: (view: T) => void
    onTogglePin: (view: T) => void
    onMenu: (view: T, anchor: RowAnchor) => void
    testID: string
}

function ViewRowInner<T extends ViewRef>({
    view,
    meta,
    position,
    pinned,
    onOpen,
    onTogglePin,
    onMenu,
    testID,
}: ViewRowProps<T>): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const menu = useMenuTrigger(view, onMenu)
    return (
        <GroupFrame position={position}>
            <View ref={menu.ref} style={[styles.row, position !== 'first' && position !== 'only' && styles.divider]}>
                <Pressable44
                    onPress={() => onOpen(view)}
                    onLongPress={menu.onLongPress}
                    accessibilityActions={menu.accessibilityActions}
                    onAccessibilityAction={menu.onAccessibilityAction}
                    accessibilityLabel={meta ? `${view.name}, ${meta}` : view.name}
                    pressedBackground={colors.sunken}
                    style={styles.open}
                    testID={testID}
                >
                    <View style={styles.iconTile}>
                        <ViewIcon kind={view.kind} size={17} />
                    </View>
                    <View style={styles.text}>
                        <Text style={styles.title} numberOfLines={1}>
                            {view.name}
                        </Text>
                        {meta ? (
                            <Text style={styles.meta} numberOfLines={1}>
                                {meta}
                            </Text>
                        ) : null}
                    </View>
                </Pressable44>
                {pinned !== null ? (
                    <Pressable44
                        onPress={() => onTogglePin(view)}
                        accessibilityLabel={pinned ? `Unpin ${view.name}` : `Pin ${view.name}`}
                        accessibilityState={{ checked: pinned }}
                        pressedBackground={colors.background}
                        hitSlop={0}
                        style={styles.pinButton}
                        testID={`${testID}-pin`}
                    >
                        <PinIcon size={20} filled={pinned} color={pinned ? colors.ink : colors.secondary} />
                    </Pressable44>
                ) : null}
            </View>
        </GroupFrame>
    )
}

export const ViewRow = memo(ViewRowInner) as typeof ViewRowInner

const useStyles = createStyles(({ colors }) => ({
    frame: {
        overflow: 'hidden',
        backgroundColor: colors.surface,
        borderColor: colors.hairline,
        borderLeftWidth: 1,
        borderRightWidth: 1,
    },
    row: {
        height: VIEW_ROW_HEIGHT - 1,
        flexDirection: 'row',
        alignItems: 'center',
        paddingRight: 4,
        backgroundColor: colors.surface,
    },
    divider: {
        borderTopWidth: 1,
        borderTopColor: colors.rowDivider,
    },
    open: {
        flex: 1,
        minWidth: 0,
        alignSelf: 'stretch',
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        paddingLeft: 12,
    },
    iconTile: {
        width: 32,
        height: 32,
        borderRadius: radii.markLarge,
        backgroundColor: colors.sunken,
        alignItems: 'center',
        justifyContent: 'center',
    },
    text: {
        flex: 1,
        minWidth: 0,
    },
    title: {
        ...type.bodySmallStrong,
        lineHeight: 20,
        color: colors.ink,
    },
    meta: {
        ...type.meta,
        color: colors.tertiary,
    },
    pinButton: {
        width: 44,
        height: 44,
        borderRadius: radii.pill,
        alignItems: 'center',
        justifyContent: 'center',
    },
}))
