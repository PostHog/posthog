import { type ReactElement, useCallback, useEffect, useRef, useState } from 'react'
import { AccessibilityInfo, Platform, Text, View } from 'react-native'
import Animated, { FadeIn, FadeOut } from 'react-native-reanimated'
import { OverlayPortal } from '@/ui/OverlayPortal'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useTheme } from '@/ui/theme'
import { radii } from '@/ui/tokens'
import { useOverlayPane } from '@/ui/useOverlayPane'
import { bottomOffset, useScreenInsets } from '@/ui/useScreenInsets'

const SHOW_MS = 2600
/** Long enough to read a second line. */
const SHOW_WITH_DETAIL_MS = 3600
/** Long enough to reach Undo after reading the message. */
const SHOW_WITH_UNDO_MS = 4500

export interface ToastMessage {
    id: number
    text: string
    undo?: () => void
    /** A smaller second line under the message. */
    detail?: string
}

export interface Toasts {
    toast: ToastMessage | null
    show: (text: string, undo?: () => void, detail?: string) => void
    hide: () => void
}

/** One toast at a time: a new message replaces the old one. */
export function useToasts(): Toasts {
    const [toast, setToast] = useState<ToastMessage | null>(null)
    const counter = useRef(0)
    const show = useCallback((text: string, undo?: () => void, detail?: string) => {
        counter.current += 1
        setToast({ id: counter.current, text, undo, detail })
        AccessibilityInfo.announceForAccessibility(detail ? `${text}. ${detail}` : text)
    }, [])
    const hide = useCallback(() => setToast(null), [])
    useEffect(() => {
        if (!toast) {
            return undefined
        }
        const timer = setTimeout(
            () => setToast(null),
            toast.undo ? SHOW_WITH_UNDO_MS : toast.detail ? SHOW_WITH_DETAIL_MS : SHOW_MS
        )
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
 * A dark pill that confirms a pin change and can undo it, or confirms an account change with a second line. It draws through the nearest `OverlayHost`, so a toast from
 * a view's header still sits at the bottom of the screen, above the tab bar and any open sheet.
 */
export function ViewsToast({
    toast,
    onHide,
    bottom = Platform.OS === 'ios' ? 50 : 114,
}: ViewsToastProps): ReactElement | null {
    const { colors, shadows } = useTheme()
    const styles = useStyles()
    const insets = useScreenInsets()
    const pane = useOverlayPane()
    if (!toast) {
        return null
    }
    const { undo, detail } = toast
    return (
        <OverlayPortal>
            <View
                pointerEvents="box-none"
                style={{ position: 'absolute', left: pane.x, top: pane.y, width: pane.width, height: pane.height }}
            >
                <Animated.View
                    key={toast.id}
                    entering={FadeIn.duration(180)}
                    exiting={FadeOut.duration(180)}
                    style={[
                        styles.toast,
                        shadows.card,
                        { bottom: bottomOffset(insets, bottom) },
                        undo ? null : styles.solo,
                        detail ? styles.twoLines : null,
                    ]}
                    accessibilityLiveRegion="polite"
                    testID="views-toast"
                >
                    {detail ? (
                        <View style={styles.lines}>
                            <Text style={styles.text}>{toast.text}</Text>
                            <Text style={styles.detail} testID="views-toast-detail">
                                {detail}
                            </Text>
                        </View>
                    ) : (
                        <Text style={styles.text}>{toast.text}</Text>
                    )}
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
            </View>
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
    twoLines: {
        paddingVertical: 10,
        borderRadius: radii.sheet,
    },
    lines: {
        flexShrink: 1,
    },
    text: {
        flexShrink: 1,
        fontSize: 15,
        lineHeight: 20,
        fontWeight: '600',
        color: colors.onInk,
    },
    detail: {
        fontSize: 13,
        lineHeight: 18,
        color: colors.onInk,
        opacity: 0.75,
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
