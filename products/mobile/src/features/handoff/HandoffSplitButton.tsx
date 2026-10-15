import { type ReactElement, useState } from 'react'
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native'

import { useAsyncAction } from '@/lib/useAsyncAction'
import { POSTHOG_AGENT } from '@/model/agent'
import type { ReportView } from '@/model/types'
import { ChevronDownIcon } from '@/ui/icons/ChevronDownIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { colors, fonts, radii, type } from '@/ui/tokens'

import { openExternalHandoff } from './externalHandoff'
import { handoffAgentName, useHandoffPreferenceStore } from './handoffPreferenceStore'

interface HandoffSplitButtonProps {
    report: ReportView
    onHandOff: () => void
    onOpenPicker: () => void
    pending: boolean
}

export function HandoffSplitButton({
    report,
    onHandOff,
    onOpenPicker,
    pending,
}: HandoffSplitButtonProps): ReactElement {
    const target = useHandoffPreferenceStore((state) => state.target)
    const agentName = handoffAgentName(target)
    const [error, setError] = useState<string | null>(null)
    const handOff = useAsyncAction(async () => {
        if (pending) {
            return
        }
        setError(null)
        if (target === 'posthog') {
            onHandOff()
            return
        }
        try {
            await openExternalHandoff(target, report)
        } catch (cause) {
            setError((cause as Error).message)
        }
    })
    const busy = pending || handOff.pending
    return (
        <>
            {error ? (
                <Text style={styles.error} accessibilityRole="alert" testID="handoff-launch-error">
                    {error}
                </Text>
            ) : null}
            <View style={styles.button}>
                <Pressable44
                    onPress={() => void handOff.run()}
                    disabled={busy}
                    haptic="light"
                    accessibilityLabel={`Hand off to ${agentName}`}
                    accessibilityState={{ busy, disabled: busy }}
                    pressedBackground={colors.pressOverlay}
                    style={styles.main}
                    testID="handoff-button"
                >
                    {target === 'posthog' ? (
                        <View style={styles.mark}>
                            {busy ? (
                                <ActivityIndicator size="small" color={colors.white} />
                            ) : (
                                <Text style={styles.markText}>{POSTHOG_AGENT.mark}</Text>
                            )}
                        </View>
                    ) : busy ? (
                        <ActivityIndicator size="small" color={colors.white} />
                    ) : null}
                    <Text style={styles.label} numberOfLines={1}>
                        Hand off to {agentName}
                    </Text>
                </Pressable44>
                <Pressable44
                    onPress={onOpenPicker}
                    disabled={busy}
                    accessibilityLabel="Choose how to hand off"
                    pressedBackground={colors.pressOverlay}
                    style={styles.chevron}
                    testID="handoff-picker-button"
                >
                    <ChevronDownIcon size={14} color={colors.white} strokeWidth={2.6} />
                </Pressable44>
            </View>
        </>
    )
}

const styles = StyleSheet.create({
    error: { ...type.metaSmall, color: colors.orange, paddingHorizontal: 4 },
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
