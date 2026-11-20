import { type ReactElement, type ReactNode, useLayoutEffect } from 'react'
import { Text, View } from 'react-native'

import { MicrophoneIcon } from '@/ui/icons/MicrophoneIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, type } from '@/ui/tokens'

import type { useChatDictation } from './useChatDictation'

export type ComposerDictation = ReturnType<typeof useChatDictation>

interface ComposerInputProps {
    children: ReactNode
    compact?: boolean
    dictation: ComposerDictation
}

export function ComposerInput({ children, compact, dictation }: ComposerInputProps): ReactElement {
    const styles = useStyles()
    const { cancel, error, phase, preview } = dictation
    useLayoutEffect(() => cancel, [cancel])

    const status =
        error ??
        {
            idle: null,
            starting: 'Starting dictation…',
            listening: 'Listening…',
            finishing: 'Finishing dictation…',
        }[phase]

    return (
        <View style={compact && styles.compact}>
            {children}
            {preview && !error ? (
                <View collapsable={false} importantForAccessibility="no" accessibilityLabel="ph-no-capture">
                    <Text style={styles.feedback} numberOfLines={compact ? 1 : 2} testID="chat-dictation-preview">
                        {preview}
                    </Text>
                </View>
            ) : status ? (
                <Text
                    style={styles.feedback}
                    accessibilityLiveRegion="polite"
                    accessibilityRole={error ? 'alert' : undefined}
                    testID="chat-dictation-status"
                >
                    {status}
                </Text>
            ) : null}
        </View>
    )
}

interface DictationButtonProps {
    dictation: ComposerDictation
    disabled: boolean
}

export function DictationButton({ dictation, disabled }: DictationButtonProps): ReactElement | null {
    const colors = useColors()
    const styles = useStyles()
    const { available, phase, toggle } = dictation
    if (!available) return null

    const recording = phase === 'starting' || phase === 'listening'
    const busy = phase === 'finishing'
    const micDisabled = disabled || busy
    return (
        <Pressable44
            accessibilityLabel={recording ? 'Stop dictation' : busy ? 'Finishing dictation' : 'Start dictation'}
            accessibilityState={{ disabled: micDisabled, busy, selected: recording }}
            disabled={micDisabled}
            onPress={toggle}
            pressedBackground={recording ? colors.inkHover : colors.pressed}
            style={[styles.button, recording && styles.recording, micDisabled && styles.disabled]}
            testID="chat-dictation"
        >
            {recording ? <View style={styles.stopSquare} /> : <MicrophoneIcon size={iconSizes.control} />}
        </Pressable44>
    )
}

const useStyles = createStyles(({ colors }) => ({
    compact: { flex: 1, minWidth: 100 },
    button: {
        width: 40,
        height: 40,
        borderRadius: 20,
        alignItems: 'center',
        justifyContent: 'center',
    },
    recording: { backgroundColor: colors.ink },
    disabled: { opacity: 0.4 },
    stopSquare: { width: 12, height: 12, borderRadius: 2, backgroundColor: colors.onInk },
    feedback: { ...type.meta, color: colors.muted, paddingHorizontal: 6, paddingTop: 4 },
}))
