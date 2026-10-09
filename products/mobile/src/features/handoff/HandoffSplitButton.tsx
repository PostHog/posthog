import type { ReactElement } from 'react'
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native'

import type { AgentBadge } from '@/model/types'
import { ChevronDownIcon } from '@/ui/icons/ChevronDownIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { colors, fonts, radii, type } from '@/ui/tokens'

interface HandoffSplitButtonProps {
    agent: AgentBadge
    onHandOff: () => void
    onOpenPicker: () => void
    pending: boolean
}

export function HandoffSplitButton({ agent, onHandOff, onOpenPicker, pending }: HandoffSplitButtonProps): ReactElement {
    return (
        <View style={styles.button}>
            <Pressable44
                onPress={onHandOff}
                disabled={pending}
                haptic="light"
                accessibilityLabel={`Hand off to ${agent.name}`}
                accessibilityState={{ busy: pending, disabled: pending }}
                pressedBackground={colors.pressOverlay}
                style={styles.main}
                testID="handoff-button"
            >
                <View style={styles.mark}>
                    {pending ? (
                        <ActivityIndicator size="small" color={colors.white} />
                    ) : (
                        <Text style={styles.markText}>{agent.mark}</Text>
                    )}
                </View>
                <Text style={styles.label} numberOfLines={1}>
                    Hand off to {agent.name}
                </Text>
            </Pressable44>
            <Pressable44
                onPress={onOpenPicker}
                accessibilityLabel="Choose how to hand off"
                pressedBackground={colors.pressOverlay}
                style={styles.chevron}
                testID="handoff-picker-button"
            >
                <ChevronDownIcon size={14} color={colors.white} strokeWidth={2.6} />
            </Pressable44>
        </View>
    )
}

const styles = StyleSheet.create({
    button: {
        flexDirection: 'row',
        height: 52,
        borderRadius: radii.card,
        backgroundColor: colors.orange,
        overflow: 'hidden',
    },
    main: {
        flex: 1,
        minWidth: 0,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 10,
        paddingHorizontal: 12,
    },
    mark: {
        width: 24,
        height: 24,
        borderRadius: radii.markSmall,
        backgroundColor: colors.onAccentTile,
        alignItems: 'center',
        justifyContent: 'center',
    },
    markText: {
        fontFamily: fonts.mono,
        fontSize: 11,
        fontWeight: '600',
        color: colors.white,
    },
    label: {
        ...type.button,
        color: colors.white,
        flexShrink: 1,
    },
    chevron: {
        width: 56,
        borderLeftWidth: 1,
        borderLeftColor: colors.onAccentDivider,
        alignItems: 'center',
        justifyContent: 'center',
    },
})
