import { type ReactElement, useEffect } from 'react'
import { StyleSheet, Text, View } from 'react-native'

import { OverlayPortal } from '@/ui/OverlayPortal'
import { Pressable44 } from '@/ui/Pressable44'
import { colors, radii, shadows, type } from '@/ui/tokens'
import { bottomOffset, useScreenInsets } from '@/ui/useScreenInsets'

const TOAST_MS = 4000

export interface ViewToastMessage {
    /** Changes for every new toast, so the same text shown twice restarts the timer. */
    id: number
    text: string
    actionLabel?: string
    onAction?: () => void
}

interface ViewToastProps {
    toast: ViewToastMessage | null
    onDone: () => void
}

/** A dark pill at the bottom of a view screen that confirms an action and can offer Undo. */
export function ViewToast({ toast, onDone }: ViewToastProps): ReactElement | null {
    const insets = useScreenInsets()
    const id = toast?.id
    useEffect(() => {
        if (id === undefined) {
            return undefined
        }
        const timer = setTimeout(onDone, TOAST_MS)
        return () => clearTimeout(timer)
    }, [id, onDone])

    if (!toast) {
        return null
    }
    const { actionLabel, onAction } = toast
    return (
        <OverlayPortal>
            <View style={[styles.wrap, { bottom: bottomOffset(insets, 34) }]} pointerEvents="box-none">
                <View
                    style={[styles.toast, shadows.card, !actionLabel && styles.solo]}
                    accessibilityLiveRegion="polite"
                    testID="view-toast"
                >
                    <Text style={styles.text} numberOfLines={1}>
                        {toast.text}
                    </Text>
                    {actionLabel && onAction ? (
                        <Pressable44
                            onPress={() => {
                                onAction()
                                onDone()
                            }}
                            style={styles.action}
                            pressedBackground={colors.darkDivider}
                            testID="view-toast-action"
                        >
                            <Text style={styles.actionText}>{actionLabel}</Text>
                        </Pressable44>
                    ) : null}
                </View>
            </View>
        </OverlayPortal>
    )
}

const styles = StyleSheet.create({
    wrap: {
        position: 'absolute',
        left: 20,
        right: 20,
        alignItems: 'center',
        zIndex: 40,
    },
    toast: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        minHeight: 44,
        maxWidth: '100%',
        paddingVertical: 7,
        paddingLeft: 18,
        paddingRight: 7,
        borderRadius: radii.pill,
        backgroundColor: colors.ink,
    },
    solo: {
        paddingRight: 18,
    },
    text: {
        ...type.bodySmallStrong,
        color: colors.white,
        flexShrink: 1,
    },
    action: {
        height: 30,
        paddingHorizontal: 12,
        borderRadius: radii.pill,
        backgroundColor: colors.onAccentTile,
        alignItems: 'center',
        justifyContent: 'center',
    },
    actionText: {
        fontSize: 14,
        fontWeight: '600',
        color: colors.white,
    },
})
