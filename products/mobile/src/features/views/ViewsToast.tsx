import { type ReactElement, useCallback, useEffect, useRef, useState } from 'react'
import { AccessibilityInfo, Text } from 'react-native'
import Animated, { FadeIn, FadeOut } from 'react-native-reanimated'

import { OverlayPortal } from '@/ui/OverlayPortal'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useTheme } from '@/ui/theme'
import { radii } from '@/ui/tokens'
import { bottomOffset, useScreenInsets } from '@/ui/useScreenInsets'

const SHOW_MS = 2600
/** Long enough to reach Undo after reading the message. */
const SHOW_WITH_UNDO_MS = 4500

export interface ToastMessage {
    id: number
    text: string
    undo?: () => void
}

export interface Toasts {
    toast: ToastMessage | null
    show: (text: string, undo?: () => void) => void
    hide: () => void
}

/** One toast at a time: a new message replaces the old one. */
export function useToasts(): Toasts {
    const [toast, setToast] = useState<ToastMessage | null>(null)
    const counter = useRef(0)
    const show = useCallback((text: string, undo?: () => void) => {
        counter.current += 1
        setToast({ id: counter.current, text, undo })
        AccessibilityInfo.announceForAccessibility(text)
    }, [])
    const hide = useCallback(() => setToast(null), [])
    useEffect(() => {
        if (!toast) {
            return undefined
        }
        const timer = setTimeout(() => setToast(null), toast.undo ? SHOW_WITH_UNDO_MS : SHOW_MS)
        return () => clearTimeout(timer)
    }, [toast])
    return { toast, show, hide }
}

interface ViewsToastProps {
    toast: ToastMessage | null
    onHide: () => void
    /** Design-frame distance from the bottom edge: above the bottom bar on a tab, lower on a pushed screen. */
    bottom?: number
}

/**
 * A dark pill that confirms a pin change and can undo it. It draws through the nearest `OverlayHost`, so a toast from
 * a view's header still sits at the bottom of the screen, above the tab bar and any open sheet.
 */
export function ViewsToast({ toast, onHide, bottom = 114 }: ViewsToastProps): ReactElement | null {
    const { colors, shadows } = useTheme()
    const styles = useStyles()
    const insets = useScreenInsets()
    if (!toast) {
        return null
    }
    const { undo } = toast
    return (
        <OverlayPortal>
            <Animated.View
                key={toast.id}
                entering={FadeIn.duration(180)}
                exiting={FadeOut.duration(180)}
                style={[
                    styles.toast,
                    shadows.card,
                    { bottom: bottomOffset(insets, bottom) },
                    undo ? null : styles.solo,
                ]}
                accessibilityLiveRegion="polite"
                testID="views-toast"
            >
                <Text style={styles.text} numberOfLines={1}>
                    {toast.text}
                </Text>
                {undo ? (
                    <Pressable44
                        onPress={() => {
                            onHide()
                            undo()
                        }}
                        accessibilityLabel="Undo"
                        pressedBackground={colors.inkHover}
                        style={styles.undo}
                        testID="views-toast-undo"
                    >
                        <Text style={styles.undoText}>Undo</Text>
                    </Pressable44>
                ) : null}
            </Animated.View>
        </OverlayPortal>
    )
}

const useStyles = createStyles(({ colors }) => ({
    toast: {
        position: 'absolute',
        alignSelf: 'center',
        maxWidth: '90%',
        minHeight: 44,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        paddingVertical: 8,
        paddingLeft: 18,
        paddingRight: 8,
        borderRadius: radii.pill,
        backgroundColor: colors.ink,
        zIndex: 25,
    },
    solo: {
        paddingRight: 18,
    },
    text: {
        flexShrink: 1,
        fontSize: 15,
        fontWeight: '600',
        color: colors.onInk,
    },
    undo: {
        height: 30,
        paddingHorizontal: 12,
        borderRadius: radii.pill,
        backgroundColor: colors.onAccentTile,
        alignItems: 'center',
        justifyContent: 'center',
    },
    undoText: {
        fontSize: 14,
        fontWeight: '600',
        color: colors.onInk,
    },
}))
