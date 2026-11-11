import type { ReactElement } from 'react'
import { ActivityIndicator, Text, View } from 'react-native'

import { BottomSheet } from '@/ui/BottomSheet'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

interface SuppressSheetProps {
    visible: boolean
    pending: boolean
    onClose: () => void
    onConfirm: () => void
}

/** Suppress asks first, with the web's own description of what it does (`ISSUE_STATUS_CONFIG.suppressed`). */
export function SuppressSheet({ visible, pending, onClose, onConfirm }: SuppressSheetProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    return (
        <BottomSheet
            visible={visible}
            onClose={onClose}
            accessibilityLabel="Suppress this issue?"
            testID="suppress-sheet"
        >
            <Text style={styles.title} accessibilityRole="header">
                Suppress this issue?
            </Text>
            <Text style={styles.description}>New occurrences of this issue are ignored.</Text>
            <View style={styles.buttons}>
                <Pressable44
                    onPress={onConfirm}
                    disabled={pending}
                    accessibilityRole="button"
                    accessibilityLabel="Suppress"
                    accessibilityState={{ disabled: pending, busy: pending }}
                    pressedBackground={colors.inkHover}
                    style={[styles.button, styles.confirm]}
                    testID="suppress-confirm"
                >
                    {pending ? (
                        <ActivityIndicator size="small" color={colors.onInk} />
                    ) : (
                        <Text style={styles.confirmText}>Suppress</Text>
                    )}
                </Pressable44>
                <Pressable44
                    onPress={onClose}
                    accessibilityRole="button"
                    accessibilityLabel="Cancel"
                    pressedBackground={colors.background}
                    style={[styles.button, styles.cancel]}
                    testID="suppress-cancel"
                >
                    <Text style={styles.cancelText}>Cancel</Text>
                </Pressable44>
            </View>
        </BottomSheet>
    )
}

const useStyles = createStyles(({ colors }) => ({
    title: {
        ...type.sheetTitle,
        color: colors.ink,
        marginTop: 18,
        paddingHorizontal: 4,
    },
    description: {
        ...type.metaSmall,
        color: colors.muted,
        marginTop: 6,
        paddingHorizontal: 4,
    },
    buttons: {
        marginTop: 20,
        gap: 10,
    },
    button: {
        height: 52,
        borderRadius: radii.pill,
        alignItems: 'center',
        justifyContent: 'center',
    },
    confirm: {
        backgroundColor: colors.ink,
    },
    confirmText: {
        ...type.button,
        color: colors.onInk,
    },
    cancel: {
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
    },
    cancelText: {
        ...type.button,
        color: colors.ink,
    },
}))
