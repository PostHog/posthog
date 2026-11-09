import type { ComponentType, ReactElement } from 'react'
import { Text, View } from 'react-native'

import { BlurEdge } from '@/ui/BlurEdge'
import { FadeEdge } from '@/ui/FadeEdge'
import { ComposeIcon } from '@/ui/icons/ComposeIcon'
import { ErrorTriangleIcon } from '@/ui/icons/ErrorTriangleIcon'
import { HomeIcon } from '@/ui/icons/HomeIcon'
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

export type BottomBarSlot = 'home' | 'chats' | 'views' | NavPin

interface BottomBarProps {
    selected: BottomBarSlot
    /** Slots after Views, in pin order. */
    pins: readonly NavPin[]
    onHome: () => void
    onChats: () => void
    onViews: () => void
    onPin: (pin: NavPin) => void
    onNewChat?: () => void
}

const BAR_GUTTER = 20
const BAR_GAP = 10
const SLOT_MIN = 44

function ErrorsNavIcon(props: IconProps): ReactElement {
    return <ErrorTriangleIcon strokeWidth={2} {...props} />
}

function ReplayNavIcon(props: IconProps): ReactElement {
    return <RecordingIcon strokeWidth={2} {...props} />
}

const PIN_SLOTS: Record<NavPin, { label: string; Icon: ComponentType<IconProps> }> = {
    errors: { label: 'Errors', Icon: ErrorsNavIcon },
    replay: { label: 'Sessions', Icon: ReplayNavIcon },
}

interface NavSlotProps {
    label: string
    Icon: ComponentType<IconProps>
    onPress: () => void
    disabled?: boolean
    testID: string
}

function NavSlot({ label, Icon, onPress, disabled = false, testID }: NavSlotProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const { rail } = useAppLayout()
    return (
        <Pressable44
            onPress={onPress}
            disabled={disabled}
            accessibilityRole="tab"
            accessibilityLabel={label}
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
            <Icon size={iconSizes.navigation} />
        </Pressable44>
    )
}

interface SelectedSlotProps {
    onPress: () => void
    label: string
    Icon: ComponentType<IconProps>
    testID: string
}

function SelectedSlot({ label, Icon, testID, onPress }: SelectedSlotProps): ReactElement {
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
            accessibilityState={{ selected: true }}
            testID={testID}
        >
            <Icon size={iconSizes.navigation} />
        </Pressable44>
    )
}

export function BottomBar({
    selected,
    pins,
    onHome,
    onChats,
    onViews,
    onPin,
    onNewChat,
}: BottomBarProps): ReactElement {
    const { colors, shadows } = useTheme()
    const styles = useStyles()
    const insets = useScreenInsets()
    const { rail, railSide, contentWidth } = useAppLayout()
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
                        height: (3 + pins.length) * 52 + 12,
                        width: 64,
                        flexDirection: 'column',
                        paddingVertical: 8,
                        gap: 6,
                    },
                ]}
                accessibilityRole="tablist"
            >
                {selected === 'home' ? (
                    <SelectedSlot onPress={onHome} label="Home" Icon={HomeIcon} testID="inbox-nav-home" />
                ) : (
                    <NavSlot label="Home" Icon={HomeIcon} onPress={onHome} testID="inbox-nav-home" />
                )}
                {/* The testID keeps its old name because the Argent flows select this slot by it. */}
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
                        rail && { width: 56, paddingLeft: 0, paddingRight: 0, justifyContent: 'center' },
                    ]}
                    haptic="selection"
                    testID="inbox-chat"
                >
                    <ComposeIcon size={iconSizes.navigation} color={colors.onInk} />
                    {rail ? null : <Text style={styles.chatText}>Chat</Text>}
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
