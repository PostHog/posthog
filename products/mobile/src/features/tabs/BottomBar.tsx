import type { ComponentType, ReactElement } from 'react'
import { Text, useWindowDimensions, View } from 'react-native'

import { BlurEdge } from '@/ui/BlurEdge'
import { FadeEdge } from '@/ui/FadeEdge'
import { ComposeIcon } from '@/ui/icons/ComposeIcon'
import { ErrorTriangleIcon } from '@/ui/icons/ErrorTriangleIcon'
import { GlobeIcon } from '@/ui/icons/GlobeIcon'
import { HomeIcon } from '@/ui/icons/HomeIcon'
import { InboxIcon } from '@/ui/icons/InboxIcon'
import { RecordingIcon } from '@/ui/icons/RecordingIcon'
import { SpacesIcon } from '@/ui/icons/SpacesIcon'
import type { IconProps } from '@/ui/icons/types'
import { ViewsIcon } from '@/ui/icons/ViewsIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors, useTheme } from '@/ui/theme'
import { iconSizes, layout, radii, type } from '@/ui/tokens'
import { useAppLayout } from '@/ui/useAppLayout'
import { bottomOffset, useScreenInsets } from '@/ui/useScreenInsets'

import type { NavPin } from './navPinStore'

export type BottomBarSlot = 'home' | 'inbox' | 'chats' | 'views' | NavPin

interface BottomBarProps {
    selected: BottomBarSlot
    /** Slots after Views, in pin order. */
    pins: readonly NavPin[]
    /** Draws a dot on the Inbox slot. */
    inboxUnread: boolean
    onHome: () => void
    onInbox: () => void
    onChats: () => void
    onViews: () => void
    onPin: (pin: NavPin) => void
    onNewChat?: () => void
}

const BAR_GUTTER = 20
const BAR_GAP = 10
const SLOT_MIN = 44
const UNREAD_DOT = 8

function ErrorsNavIcon(props: IconProps): ReactElement {
    return <ErrorTriangleIcon strokeWidth={2} {...props} />
}

function ReplayNavIcon(props: IconProps): ReactElement {
    return <RecordingIcon strokeWidth={2} {...props} />
}

function WebAnalyticsNavIcon(props: IconProps): ReactElement {
    return <GlobeIcon strokeWidth={2} {...props} />
}

const PIN_SLOTS: Record<NavPin, { label: string; Icon: ComponentType<IconProps> }> = {
    errors: { label: 'Errors', Icon: ErrorsNavIcon },
    replay: { label: 'Sessions', Icon: ReplayNavIcon },
    web_analytics: { label: 'Web analytics', Icon: WebAnalyticsNavIcon },
}

interface SlotIconProps {
    Icon: ComponentType<IconProps>
    unread: boolean
    testID: string
}

function SlotIcon({ Icon, unread, testID }: SlotIconProps): ReactElement {
    const styles = useStyles()
    return (
        <View>
            <Icon size={iconSizes.navigation} />
            {unread ? <View style={styles.unreadDot} testID={`${testID}-unread`} /> : null}
        </View>
    )
}

interface NavSlotProps {
    label: string
    Icon: ComponentType<IconProps>
    onPress: () => void
    disabled?: boolean
    unread?: boolean
    testID: string
}

function NavSlot({ label, Icon, onPress, disabled = false, unread = false, testID }: NavSlotProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const { rail } = useAppLayout()
    return (
        <Pressable44
            onPress={onPress}
            disabled={disabled}
            accessibilityRole="tab"
            accessibilityLabel={label}
            accessibilityValue={unread ? { text: 'Unread reports' } : undefined}
            accessibilityState={{ selected: false, disabled }}
            pressedBackground={colors.background}
            style={[
                styles.slot,
                rail && { flexBasis: 'auto', flexShrink: 0, width: 46 },
                disabled && styles.slotDisabled,
            ]}
            haptic="selection"
            testID={testID}
        >
            <SlotIcon Icon={Icon} unread={unread} testID={testID} />
        </Pressable44>
    )
}

interface SelectedSlotProps {
    onPress: () => void
    label: string
    Icon: ComponentType<IconProps>
    unread?: boolean
    testID: string
}

function SelectedSlot({ label, Icon, unread = false, testID, onPress }: SelectedSlotProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const { rail } = useAppLayout()
    return (
        <Pressable44
            onPress={onPress}
            pressedBackground={colors.background}
            style={[styles.slot, styles.slotSelected, rail && { flexBasis: 'auto', flexShrink: 0, width: 46 }]}
            accessibilityRole="tab"
            accessibilityLabel={label}
            accessibilityValue={unread ? { text: 'Unread reports' } : undefined}
            accessibilityState={{ selected: true }}
            testID={testID}
        >
            <SlotIcon Icon={Icon} unread={unread} testID={testID} />
        </Pressable44>
    )
}

export function BottomBar({
    selected,
    pins,
    inboxUnread,
    onHome,
    onInbox,
    onChats,
    onViews,
    onPin,
    onNewChat,
}: BottomBarProps): ReactElement {
    const { colors, shadows } = useTheme()
    const styles = useStyles()
    const insets = useScreenInsets()
    const { rail, railSide, contentWidth } = useAppLayout()
    const { fontScale } = useWindowDimensions()
    const navMinWidth = (4 + pins.length) * SLOT_MIN + 14
    const labeledChatWidth = 40 + iconSizes.navigation + 10 + 40 * fontScale
    const compactChat = rail || contentWidth < BAR_GUTTER * 2 + navMinWidth + BAR_GAP + labeledChatWidth
    return (
        <View
            style={[
                styles.bar,
                { paddingBottom: bottomOffset(insets, 34) },
                rail && {
                    top: insets.top + 24,
                    bottom: insets.bottom + 16,
                    left: railSide === 'left' ? 8 : contentWidth + 8,
                    right: railSide === 'right' ? 8 : undefined,
                    width: 64,
                    paddingHorizontal: 0,
                    paddingTop: 0,
                    paddingBottom: 0,
                    flexDirection: 'column',
                    justifyContent: 'flex-end',
                },
            ]}
        >
            {rail ? null : (
                <>
                    <BlurEdge direction="up" solid={0.6} />
                    <FadeEdge direction="up" solid={0.6} opacity={layout.chromeTint} />
                </>
            )}
            <View
                style={[
                    styles.nav,
                    !rail && styles.bottomNav,
                    shadows.floatingBar,
                    rail && {
                        height: (4 + pins.length) * 52 + 12,
                        width: 64,
                        flexDirection: 'column',
                        paddingVertical: 8,
                        gap: 6,
                    },
                ]}
                accessibilityRole="tablist"
            >
                {/* Home, Chats and Views keep their `inbox-nav-*` testIDs, because the Argent flows select them. */}
                {selected === 'home' ? (
                    <SelectedSlot onPress={onHome} label="Home" Icon={HomeIcon} testID="inbox-nav-home" />
                ) : (
                    <NavSlot label="Home" Icon={HomeIcon} onPress={onHome} testID="inbox-nav-home" />
                )}
                {selected === 'inbox' ? (
                    <SelectedSlot
                        onPress={onInbox}
                        label="Inbox"
                        Icon={InboxIcon}
                        unread={inboxUnread}
                        testID="nav-inbox"
                    />
                ) : (
                    <NavSlot label="Inbox" Icon={InboxIcon} onPress={onInbox} unread={inboxUnread} testID="nav-inbox" />
                )}
                {selected === 'chats' ? (
                    <SelectedSlot onPress={onChats} label="Chats" Icon={SpacesIcon} testID="inbox-nav-chat" />
                ) : (
                    <NavSlot label="Chats" Icon={SpacesIcon} onPress={onChats} testID="inbox-nav-chat" />
                )}
                {selected === 'views' ? (
                    <SelectedSlot onPress={onViews} label="Views" Icon={ViewsIcon} testID="inbox-nav-views" />
                ) : (
                    <NavSlot label="Views" Icon={ViewsIcon} onPress={onViews} testID="inbox-nav-views" />
                )}
                {pins.map((pin) => {
                    const { label, Icon } = PIN_SLOTS[pin]
                    return selected === pin ? (
                        <SelectedSlot
                            onPress={() => onPin(pin)}
                            key={pin}
                            label={label}
                            Icon={Icon}
                            testID={`nav-pin-${pin}`}
                        />
                    ) : (
                        <NavSlot
                            key={pin}
                            label={label}
                            Icon={Icon}
                            onPress={() => onPin(pin)}
                            testID={`nav-pin-${pin}`}
                        />
                    )
                })}
            </View>
            {onNewChat ? (
                <Pressable44
                    onPress={onNewChat}
                    accessibilityLabel="Chat"
                    pressedBackground={colors.inkHover}
                    style={[
                        styles.chat,
                        shadows.fab,
                        compactChat && { width: 56, paddingLeft: 0, paddingRight: 0, justifyContent: 'center' },
                    ]}
                    haptic="selection"
                    testID="inbox-chat"
                >
                    <ComposeIcon size={iconSizes.navigation} color={colors.onInk} />
                    {compactChat ? null : <Text style={styles.chatText}>Chat</Text>}
                </Pressable44>
            ) : null}
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    bar: {
        position: 'absolute',
        left: 0,
        right: 0,
        bottom: 0,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: BAR_GAP,
        paddingTop: 28,
        paddingHorizontal: BAR_GUTTER,
        pointerEvents: 'box-none',
    },
    // 54pt content box plus 4pt padding and a 1pt border on each side.
    nav: {
        alignItems: 'center',
        justifyContent: 'space-around',
        backgroundColor: colors.surface,
        borderWidth: 1,
        borderColor: colors.border,
        borderRadius: radii.pill,
        paddingVertical: 4,
        paddingHorizontal: 6,
    },
    bottomNav: {
        flex: 1,
        height: 64,
        flexDirection: 'row',
    },
    // Slots shrink below the handoff's 72pt on phones narrower than the 402pt prototype frame, never below 44pt.
    slot: {
        flexBasis: 72,
        flexShrink: 1,
        minWidth: SLOT_MIN,
        height: 46,
        borderRadius: radii.pill,
        alignItems: 'center',
        justifyContent: 'center',
    },
    slotSelected: {
        backgroundColor: colors.sunken,
    },
    slotDisabled: {
        opacity: 0.4,
    },
    unreadDot: {
        position: 'absolute',
        top: -1,
        right: -2,
        width: UNREAD_DOT,
        height: UNREAD_DOT,
        borderRadius: UNREAD_DOT / 2,
        backgroundColor: colors.blue,
    },
    // 54pt content box plus a 1pt border on each side.
    chat: {
        height: 56,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 10,
        paddingLeft: 18,
        paddingRight: 20,
        borderRadius: radii.pill,
        backgroundColor: colors.ink,
        borderWidth: 1,
        borderColor: colors.ink,
    },
    chatText: {
        ...type.button,
        color: colors.onInk,
    },
}))
