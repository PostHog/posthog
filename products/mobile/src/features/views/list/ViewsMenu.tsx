import { type ReactElement, type ReactNode, useState } from 'react'
import { type LayoutChangeEvent, Text, useWindowDimensions, View } from 'react-native'
import { useSafeAreaFrame } from 'react-native-safe-area-context'

import { placeContextMenu, type RowAnchor } from '@/features/inbox/contextMenuPlacement'
import type { PinDisplayMode, PinView, ViewRef } from '@/model/views'
import { FloatingCard } from '@/ui/FloatingCard'
import { ArrowDownIcon } from '@/ui/icons/ArrowDownIcon'
import { ArrowUpIcon } from '@/ui/icons/ArrowUpIcon'
import { ChevronRightIcon } from '@/ui/icons/ChevronRightIcon'
import { PinIcon } from '@/ui/icons/PinIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { layout, type } from '@/ui/tokens'
import { bottomOffset, topOffset, useScreenInsets } from '@/ui/useScreenInsets'

import { TABS_HEADER_BOTTOM } from '../../tabs/TabsHeader'
import { ModeSegment } from './ModeSegment'

/** The bottom bar's design inset, the same one the list pads its content by. */
const BOTTOM_BAR_ZONE = 120
const CARD_BORDER = 1
const MENU_WIDTH = 268

interface MenuCardProps {
    visible: boolean
    anchor: RowAnchor
    onClose: () => void
    accessibilityLabel: string
    testID: string
    children: ReactNode
}

/** A floating menu next to a row, measured before it shows so it never lands at a spot picked without its height. */
export function MenuCard({
    visible,
    anchor,
    onClose,
    accessibilityLabel,
    testID,
    children,
}: MenuCardProps): ReactElement {
    const styles = useStyles()
    const insets = useScreenInsets()
    const { width: windowWidth } = useWindowDimensions()
    // The overlay covers the full screen, which on Android edge-to-edge includes the navigation bar.
    const { height: screenHeight } = useSafeAreaFrame()
    const [height, setHeight] = useState<number | null>(null)
    const [wasVisible, setWasVisible] = useState(visible)
    const [opens, setOpens] = useState(0)
    // A reopened menu can have other rows, so it is measured again before its first frame. The content remounts on
    // each open, so `onLayout` fires even when the card is still mounted from the last exit animation.
    if (visible !== wasVisible) {
        setWasVisible(visible)
        if (visible) {
            setHeight(null)
            setOpens(opens + 1)
        }
    }
    const placement = placeContextMenu({
        rowTop: anchor.y,
        rowBottom: anchor.y + anchor.height,
        menuHeight: height ?? 0,
        topLimit: topOffset(insets, TABS_HEADER_BOTTOM),
        bottomLimit: screenHeight - bottomOffset(insets, BOTTOM_BAR_ZONE),
    })
    const top = height === null ? -screenHeight : placement.top
    const left = Math.max(layout.inboxGutter, Math.min(anchor.x, windowWidth - layout.inboxGutter - MENU_WIDTH))
    const onLayout = (event: LayoutChangeEvent): void => {
        setHeight(event.nativeEvent.layout.height + CARD_BORDER * 2)
    }
    const origin = placement.side === 'below' ? 'top left' : 'bottom left'
    return (
        <FloatingCard
            visible={visible}
            onClose={onClose}
            transformOrigin={origin}
            accessibilityLabel={accessibilityLabel}
            testID={testID}
            style={[styles.card, { left, top }]}
        >
            <View key={opens} style={styles.content} onLayout={onLayout}>
                {children}
            </View>
        </FloatingCard>
    )
}

interface MenuItemProps {
    label: string
    onPress: () => void
    trailing?: ReactNode
    /** Shown on the right in the tertiary color, such as the chosen tile's name. */
    meta?: string | null
    danger?: boolean
    disabled?: boolean
    testID: string
}

export function MenuItem({
    label,
    onPress,
    trailing,
    meta,
    danger = false,
    disabled = false,
    testID,
}: MenuItemProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const color = disabled ? colors.disabled : danger ? colors.diffRed : colors.ink
    return (
        <Pressable44
            onPress={onPress}
            disabled={disabled}
            accessibilityRole="menuitem"
            accessibilityLabel={meta ? `${label}, ${meta}` : label}
            pressedBackground={colors.background}
            style={styles.item}
            testID={testID}
        >
            <Text style={[styles.itemLabel, { color }]} numberOfLines={1}>
                {label}
            </Text>
            {meta ? (
                <Text style={styles.itemMeta} numberOfLines={1}>
                    {meta}
                </Text>
            ) : null}
            {trailing}
        </Pressable44>
    )
}

export function MenuDivider(): ReactElement {
    const styles = useStyles()
    return <View style={styles.divider} />
}

interface PinMenuProps {
    visible: boolean
    anchor: RowAnchor
    pin: PinView
    modes: readonly PinDisplayMode[]
    /** The pin's place in the list, for Move up and Move down. */
    position: { index: number; count: number }
    /** The name of the tile a dashboard pin shows, if known. */
    tileName: string | null
    onClose: () => void
    onShowAs: (mode: PinDisplayMode) => void
    onChooseTile: () => void
    onMove: (direction: -1 | 1) => void
    onUnpin: () => void
}

/** The long-press menu of a pin: how it shows, its tile, its place and Unpin. */
export function PinMenu({
    visible,
    anchor,
    pin,
    modes,
    position,
    tileName,
    onClose,
    onShowAs,
    onChooseTile,
    onMove,
    onUnpin,
}: PinMenuProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const iconColor = (disabled: boolean): string => (disabled ? colors.disabled : colors.ink)
    const first = position.index <= 0
    const last = position.index >= position.count - 1
    return (
        <MenuCard
            visible={visible}
            anchor={anchor}
            onClose={onClose}
            accessibilityLabel={`${pin.name} actions`}
            testID="pin-menu"
        >
            {modes.length > 1 ? (
                <View style={styles.section}>
                    <Text style={styles.sectionLabel}>Show as</Text>
                    <ModeSegment
                        value={pin.display.mode}
                        available={modes}
                        onChange={onShowAs}
                        variant="labels"
                        name={pin.name}
                        testIDFor={(mode) => `pin-menu-show-${mode}`}
                    />
                </View>
            ) : null}
            {pin.kind === 'dashboard' && pin.native ? (
                <MenuItem label="Choose tile…" meta={tileName} onPress={onChooseTile} testID="pin-menu-choose-tile" />
            ) : null}
            <MenuItem
                label="Move up"
                onPress={() => onMove(-1)}
                disabled={first}
                trailing={<ArrowUpIcon size={18} color={iconColor(first)} strokeWidth={2.2} />}
                testID="pin-menu-move-up"
            />
            <MenuItem
                label="Move down"
                onPress={() => onMove(1)}
                disabled={last}
                trailing={<ArrowDownIcon size={18} color={iconColor(last)} />}
                testID="pin-menu-move-down"
            />
            <MenuDivider />
            <MenuItem
                label="Unpin"
                onPress={onUnpin}
                danger
                trailing={<PinIcon size={18} color={colors.diffRed} />}
                testID="pin-menu-unpin"
            />
        </MenuCard>
    )
}

interface RowMenuProps {
    visible: boolean
    anchor: RowAnchor
    view: ViewRef
    /** Null for views only the web can pin. */
    pinned: boolean | null
    onClose: () => void
    onTogglePin: () => void
    onOpen: () => void
}

/** The long-press menu of a Recent, Browse or search row. */
export function RowMenu({ visible, anchor, view, pinned, onClose, onTogglePin, onOpen }: RowMenuProps): ReactElement {
    const colors = useColors()
    return (
        <MenuCard
            visible={visible}
            anchor={anchor}
            onClose={onClose}
            accessibilityLabel={`${view.name} actions`}
            testID="pin-menu"
        >
            {pinned !== null ? (
                <MenuItem
                    label={pinned ? 'Unpin' : 'Pin to Views'}
                    onPress={onTogglePin}
                    danger={pinned}
                    trailing={<PinIcon size={18} filled={pinned} color={pinned ? colors.diffRed : colors.ink} />}
                    testID={pinned ? 'pin-menu-unpin' : 'pin-menu-pin'}
                />
            ) : null}
            <MenuItem
                label="Open"
                onPress={onOpen}
                trailing={<ChevronRightIcon size={13} color={colors.ink} />}
                testID="pin-menu-open"
            />
        </MenuCard>
    )
}

const useStyles = createStyles(({ colors }) => ({
    card: {
        width: MENU_WIDTH,
        borderRadius: 16,
        borderWidth: CARD_BORDER,
        borderColor: colors.hairline,
    },
    content: {
        padding: 6,
    },
    section: {
        gap: 8,
        paddingTop: 8,
        paddingHorizontal: 8,
        paddingBottom: 12,
        marginBottom: 4,
        borderBottomWidth: 1,
        borderBottomColor: colors.rowDivider,
    },
    sectionLabel: {
        fontSize: 13,
        fontWeight: '600',
        color: colors.tertiary,
    },
    item: {
        minHeight: 44,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 10,
        paddingHorizontal: 10,
        borderRadius: 10,
    },
    itemLabel: {
        ...type.body,
        flex: 1,
    },
    itemMeta: {
        ...type.meta,
        color: colors.tertiary,
        maxWidth: 128,
    },
    divider: {
        height: 1,
        marginVertical: 4,
        backgroundColor: colors.rowDivider,
    },
}))
