import { forwardRef, type ReactElement, type ReactNode } from 'react'
import { StyleSheet, Text, TextInput, View } from 'react-native'

import { ArrowUpIcon } from '@/ui/icons/ArrowUpIcon'
import { ExpandIcon } from '@/ui/icons/ExpandIcon'
import { PaperclipIcon } from '@/ui/icons/PaperclipIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { colors, inputReset, radii, shadows } from '@/ui/tokens'

interface ComposerProps {
    text: string
    onChangeText: (text: string) => void
    chips?: ReactNode
    mentionOpen: boolean
    onToggleMention: () => void
    onSend: () => void
    canSend: boolean
    isStreaming: boolean
    onStop: () => void
}

export const Composer = forwardRef<TextInput, ComposerProps>(function Composer(
    { text, onChangeText, chips, mentionOpen, onToggleMention, onSend, canSend, isStreaming, onStop },
    ref
): ReactElement {
    return (
        <View style={[styles.card, shadows.popover]}>
            {chips ? <View style={styles.chips}>{chips}</View> : null}
            <TextInput
                ref={ref}
                value={text}
                onChangeText={onChangeText}
                placeholder="Ask anything…"
                placeholderTextColor={colors.tertiary}
                style={styles.input}
                autoFocus
                multiline={false}
                returnKeyType="send"
                // Keeps the keyboard up after sending, so a follow-up is one tap away.
                submitBehavior="submit"
                onSubmitEditing={onSend}
                accessibilityLabel="Message"
                testID="chat-input"
            />
            <View style={styles.toolbar}>
                <Pressable44 disabled accessibilityLabel="Attach a file" style={[styles.tool, styles.toolDisabled]}>
                    <PaperclipIcon size={20} />
                </Pressable44>
                <Pressable44
                    onPress={onToggleMention}
                    accessibilityLabel="Add a report"
                    accessibilityState={{ expanded: mentionOpen }}
                    pressedBackground={colors.background}
                    style={[styles.tool, mentionOpen && styles.toolActive]}
                    testID="chat-mention"
                >
                    <Text style={styles.at}>@</Text>
                </Pressable44>
                <Pressable44 disabled accessibilityLabel="Expand" style={[styles.tool, styles.toolDisabled]}>
                    <ExpandIcon size={18} />
                </Pressable44>
                <View style={styles.spacer} />
                {isStreaming ? (
                    <Pressable44
                        onPress={onStop}
                        accessibilityLabel="Stop the reply"
                        pressedBackground={colors.inkHover}
                        style={[styles.send, styles.sendReady]}
                        testID="chat-stop"
                    >
                        <View style={styles.stopSquare} />
                    </Pressable44>
                ) : (
                    <Pressable44
                        onPress={onSend}
                        disabled={!canSend}
                        accessibilityLabel="Send"
                        accessibilityState={{ disabled: !canSend }}
                        style={[styles.send, canSend ? styles.sendReady : styles.sendIdle]}
                        testID="chat-send"
                    >
                        <ArrowUpIcon size={16} color={colors.white} />
                    </Pressable44>
                )}
            </View>
        </View>
    )
})

const styles = StyleSheet.create({
    card: {
        marginHorizontal: 10,
        marginBottom: 10,
        borderWidth: 1,
        borderColor: colors.hairline,
        borderRadius: radii.softCard,
        backgroundColor: colors.white,
        paddingTop: 12,
        paddingHorizontal: 12,
        paddingBottom: 10,
        gap: 10,
    },
    chips: {
        flexDirection: 'row',
        flexWrap: 'wrap',
        alignItems: 'flex-start',
        gap: 6,
    },
    input: {
        ...inputReset,
        height: 40,
        paddingHorizontal: 6,
        paddingVertical: 0,
        fontSize: 17,
        color: colors.ink,
    },
    toolbar: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 6,
    },
    tool: {
        width: 40,
        height: 40,
        borderRadius: 20,
        alignItems: 'center',
        justifyContent: 'center',
    },
    toolActive: {
        backgroundColor: colors.background,
    },
    toolDisabled: {
        opacity: 0.4,
    },
    at: {
        fontSize: 20,
        lineHeight: 24,
        fontWeight: '500',
        color: colors.ink,
    },
    spacer: {
        flex: 1,
    },
    send: {
        width: 40,
        height: 40,
        borderRadius: 20,
        alignItems: 'center',
        justifyContent: 'center',
    },
    sendReady: {
        backgroundColor: colors.ink,
    },
    sendIdle: {
        backgroundColor: colors.border,
    },
    stopSquare: {
        width: 12,
        height: 12,
        borderRadius: 2,
        backgroundColor: colors.white,
    },
})
