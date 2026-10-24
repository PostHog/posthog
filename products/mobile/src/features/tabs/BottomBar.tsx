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
    onNewChat: () => void
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
    return (
        <Pressable44
            onPress={onPress}
            disabled={disabled}
            accessibilityRole="tab"
            accessibilityLabel={label}
            accessibilityState={{ selected: false, disabled }}
            pressedBackground={colors.background}
            style={[styles.slot, disabled && styles.slotDisabled]}
            haptic="selection"
            testID={testID}
        >
            <Icon size={iconSizes.navigation} />
        </Pressable44>
    )
}

interface SelectedSlotProps {
    label: string
    Icon: ComponentType<IconProps>
    testID: string
}

function SelectedSlot({ label, Icon, testID }: SelectedSlotProps): ReactElement {
    const styles = useStyles()
    return (
        <View
            style={[styles.slot, styles.slotSelected]}
            accessibilityRole="tab"
            accessibilityLabel={label}
            accessibilityState={{ selected: true }}
            testID={testID}
        >
            <Icon size={iconSizes.navigation} />
        </View>
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
    return (
        <View style={[styles.bar, { paddingBottom: bottomOffset(insets, 34) }]}>
            <BlurEdge direction="up" solid={0.6} />
            <FadeEdge direction="up" solid={0.6} opacity={layout.chromeTint} />
            <View style={[styles.nav, shadows.floatingBar]} accessibilityRole="tablist">
                {selected === 'home' ? (
                    <SelectedSlot label="Home" Icon={HomeIcon} testID="inbox-nav-home" />
                ) : (
                    <NavSlot label="Home" Icon={HomeIcon} onPress={onHome} testID="inbox-nav-home" />
                )}
                {/* The testID keeps its old name because the Argent flows select this slot by it. */}
                {selected === 'chats' ? (
                    <SelectedSlot label="Chats" Icon={SpacesIcon} testID="inbox-nav-chat" />
                ) : (
                    <NavSlot label="Chats" Icon={SpacesIcon} onPress={onChats} testID="inbox-nav-chat" />
                )}
                {selected === 'views' ? (
                    <SelectedSlot label="Views" Icon={ViewsIcon} testID="inbox-nav-views" />
                ) : (
                    <NavSlot label="Views" Icon={ViewsIcon} onPress={onViews} testID="inbox-nav-views" />
                )}
                {pins.map((pin) => {
                    const { label, Icon } = PIN_SLOTS[pin]
                    return selected === pin ? (
                        <SelectedSlot key={pin} label={label} Icon={Icon} testID={`nav-pin-${pin}`} />
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
            <Pressable44
                onPress={onNewChat}
                accessibilityLabel="Chat"
                pressedBackground={colors.inkHover}
                style={[styles.chat, shadows.fab]}
                haptic="selection"
                testID="inbox-chat"
            >
                <ComposeIcon size={iconSizes.navigation} color={colors.onInk} />
                <Text style={styles.chatText}>Chat</Text>
            </Pressable44>
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
        flex: 1,
        height: 64,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-around',
        backgroundColor: colors.surface,
        borderWidth: 1,
        borderColor: colors.border,
        borderRadius: radii.pill,
        paddingVertical: 4,
        paddingHorizontal: 6,
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
