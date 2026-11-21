import { forwardRef, type ReactElement } from 'react'
import { ActivityIndicator, TextInput, type TextInputInstance, View } from 'react-native'

import { ArrowUpIcon } from '@/ui/icons/ArrowUpIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useTheme } from '@/ui/theme'
import { iconSizes, inputReset, radii, type } from '@/ui/tokens'

import { type ComposerDictation, ComposerInput, DictationButton } from '../ComposerInput'

interface ClassicComposerProps {
    dictation: ComposerDictation
    text: string
    onChangeText: (text: string) => void
    onSend: () => void
    onStop: () => void
    disabled: boolean
    working: boolean
    stopping: boolean
}

export const ClassicComposer = forwardRef<TextInputInstance, ClassicComposerProps>(function ClassicComposer(
    { dictation, text, onChangeText, onSend, onStop, disabled, working, stopping },
    ref
): ReactElement {
    const { colors, shadows, scheme } = useTheme()
    const styles = useStyles()
    const canSend = !disabled && !working && text.trim().length > 0 && dictation.phase === 'idle'
    return (
        <View style={[styles.card, shadows.popover]}>
            <ComposerInput dictation={dictation}>
                <TextInput
                    ref={ref}
                    value={text}
                    onChangeText={onChangeText}
                    placeholder="Ask anything…"
                    placeholderTextColor={colors.tertiary}
                    accessibilityLabel="Message"
                    keyboardAppearance={scheme}
                    multiline
                    returnKeyType="send"
                    submitBehavior="submit"
                    onSubmitEditing={() => canSend && onSend()}
                    style={styles.input}
                    testID="chat-input"
                />
            </ComposerInput>
            <View style={styles.toolbar} testID="chat-composer-actions">
                <DictationButton dictation={dictation} disabled={disabled} />
                {working ? (
                    <Pressable44
                        onPress={onStop}
                        disabled={stopping}
                        accessibilityLabel="Stop the reply"
                        accessibilityState={{ disabled: stopping }}
                        style={styles.send}
                        testID="chat-stop"
                    >
                        {stopping ? <ActivityIndicator color={colors.white} /> : <View style={styles.stopSquare} />}
                    </Pressable44>
                ) : (
                    <Pressable44
                        onPress={onSend}
                        disabled={!canSend}
                        accessibilityLabel="Send"
                        accessibilityState={{ disabled: !canSend }}
                        style={[styles.send, !canSend && styles.disabled]}
                        testID="chat-send"
                    >
                        <ArrowUpIcon size={iconSizes.control} color={canSend ? colors.onInk : colors.secondary} />
                    </Pressable44>
                )}
            </View>
        </View>
    )
})

const useStyles = createStyles(({ colors }) => ({
    card: {
        marginHorizontal: 10,
        marginBottom: 10,
        borderWidth: 1,
        borderColor: colors.hairline,
        borderRadius: radii.softCard,
        backgroundColor: colors.surface,
        padding: 12,
        gap: 10,
    },
    input: { ...inputReset, ...type.input, color: colors.ink, minHeight: 40, maxHeight: 120 },
    toolbar: { flexDirection: 'row', justifyContent: 'flex-end', alignItems: 'center', gap: 6 },
    send: {
        width: 40,
        height: 40,
        borderRadius: radii.pill,
        backgroundColor: colors.ink,
        alignItems: 'center',
        justifyContent: 'center',
    },
    disabled: { backgroundColor: colors.disabledFill },
    stopSquare: { width: 12, height: 12, borderRadius: 2, backgroundColor: colors.surface },
}))
