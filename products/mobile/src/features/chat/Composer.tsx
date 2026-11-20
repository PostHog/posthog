import { forwardRef, type ReactElement, type ReactNode } from 'react'
import type { TextInputInstance } from 'react-native'
import { ScrollView, Text, TextInput, View } from 'react-native'

import { ArrowUpIcon } from '@/ui/icons/ArrowUpIcon'
import { ChevronDownIcon } from '@/ui/icons/ChevronDownIcon'
import { PaperclipIcon } from '@/ui/icons/PaperclipIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors, useTheme } from '@/ui/theme'
import { iconSizes, inputReset, radii, type } from '@/ui/tokens'

import { MAX_ATTACHMENTS_PER_MESSAGE } from './attachments/attachmentRules'

import { type ComposerDictation, ComposerInput, DictationButton } from './ComposerInput'

interface ComposerProps {
    dictation: ComposerDictation
    dictationDisabled: boolean
    compact?: boolean
    text: string
    onChangeText: (text: string) => void
    chips?: ReactNode
    onAttach: () => void
    attachOpen: boolean
    attachDisabled: boolean
    attachFull: boolean
    mentionOpen: boolean
    onToggleMention: () => void
    modelLabel: string
    modeLabel: string
    openOption: 'model' | 'mode' | null
    optionsDisabled: boolean
    onOpenModel: () => void
    onOpenMode: () => void
    onSend: () => void
    canSend: boolean
    isStreaming: boolean
    onStop: () => void
}

interface OptionChipProps {
    label: string
    accessibilityLabel: string
    open: boolean
    disabled: boolean
    onPress: () => void
    /** False keeps the whole label, so a short label never truncates to one letter beside a long one. */
    shrinks: boolean
    testID: string
}

function OptionChip({
    label,
    accessibilityLabel,
    open,
    disabled,
    onPress,
    shrinks,
    testID,
}: OptionChipProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    return (
        <Pressable44
            onPress={onPress}
            disabled={disabled}
            accessibilityLabel={accessibilityLabel}
            accessibilityState={{ expanded: open, disabled }}
            pressedBackground={colors.background}
            style={[
                styles.chip,
                !shrinks && styles.chipFixed,
                open && styles.toolActive,
                disabled && styles.toolDisabled,
            ]}
            testID={testID}
        >
            <Text style={styles.chipLabel} numberOfLines={1}>
                {label}
            </Text>
            <View style={styles.chevron}>
                <ChevronDownIcon size={iconSizes.small} color={colors.muted} />
            </View>
        </Pressable44>
    )
}

export const Composer = forwardRef<TextInputInstance, ComposerProps>(function Composer(
    {
        compact = false,
        dictation,
        dictationDisabled,
        text,
        onChangeText,
        chips,
        onAttach,
        attachOpen,
        attachDisabled,
        attachFull,
        mentionOpen,
        onToggleMention,
        modelLabel,
        modeLabel,
        openOption,
        optionsDisabled,
        onOpenModel,
        onOpenMode,
        onSend,
        canSend,
        isStreaming,
        onStop,
    },
    ref
): ReactElement {
    const { colors, shadows, scheme } = useTheme()
    const styles = useStyles()
    const typed = text.trim().length > 0
    const showSend = !isStreaming || typed
    const stopReply = isStreaming ? (
        <Pressable44
            onPress={onStop}
            accessibilityLabel="Stop the reply"
            pressedBackground={typed ? colors.pressed : colors.inkHover}
            style={[styles.send, typed ? styles.stopSecondary : styles.sendReady]}
            testID="chat-stop"
        >
            <View style={[styles.stopSquare, typed && styles.stopSquareSecondary]} />
        </Pressable44>
    ) : null
    return (
        <View style={[styles.card, shadows.popover, compact && styles.cardCompact]}>
            {chips ? (
                compact ? (
                    <ScrollView
                        horizontal
                        style={styles.chipsCompact}
                        contentContainerStyle={styles.chips}
                        keyboardShouldPersistTaps="handled"
                        showsHorizontalScrollIndicator={false}
                    >
                        {chips}
                    </ScrollView>
                ) : (
                    <View style={styles.chips}>{chips}</View>
                )
            ) : null}
            <ComposerInput compact={compact} dictation={dictation}>
                <TextInput
                    ref={ref}
                    value={text}
                    onChangeText={onChangeText}
                    placeholder="Ask anything…"
                    placeholderTextColor={colors.tertiary}
                    keyboardAppearance={scheme}
                    style={[styles.input, compact && styles.inputCompact]}
                    multiline
                    disableFullscreenUI
                    returnKeyType="send"
                    // Keeps the keyboard up after sending, so a follow-up is one tap away.
                    submitBehavior="submit"
                    onSubmitEditing={onSend}
                    accessibilityLabel="Message"
                    testID="chat-input"
                />
            </ComposerInput>
            <View style={[styles.toolbar, compact && styles.toolbarCompact]}>
                <View style={[styles.tools, compact && styles.toolbarCompactGap]}>
                    <Pressable44
                        onPress={onAttach}
                        disabled={attachDisabled || attachFull}
                        accessibilityLabel="Attach a file"
                        accessibilityHint={
                            attachFull ? `Up to ${MAX_ATTACHMENTS_PER_MESSAGE} files fit in one message` : undefined
                        }
                        accessibilityState={{ expanded: attachOpen, disabled: attachDisabled || attachFull }}
                        pressedBackground={colors.background}
                        style={[
                            styles.tool,
                            styles.attach,
                            attachOpen && styles.toolActive,
                            (attachDisabled || attachFull) && styles.toolDisabled,
                        ]}
                        testID="chat-attach"
                    >
                        <PaperclipIcon size={iconSizes.control} />
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
                    <OptionChip
                        label={modelLabel}
                        accessibilityLabel={`Model: ${modelLabel}`}
                        open={openOption === 'model'}
                        disabled={optionsDisabled}
                        onPress={onOpenModel}
                        shrinks
                        testID="chat-model"
                    />
                    <OptionChip
                        label={modeLabel}
                        accessibilityLabel={`Mode: ${modeLabel}`}
                        open={openOption === 'mode'}
                        disabled={optionsDisabled}
                        onPress={onOpenMode}
                        shrinks={false}
                        testID="chat-mode"
                    />
                </View>
                <View style={[styles.actions, compact && styles.toolbarCompactGap]} testID="chat-composer-actions">
                    {showSend ? stopReply : null}
                    <DictationButton dictation={dictation} disabled={dictationDisabled} />
                    {showSend ? (
                        <Pressable44
                            onPress={onSend}
                            disabled={!canSend}
                            accessibilityLabel="Send"
                            accessibilityState={{ disabled: !canSend }}
                            style={[styles.send, canSend ? styles.sendReady : styles.sendIdle]}
                            testID="chat-send"
                        >
                            <ArrowUpIcon size={iconSizes.control} color={canSend ? colors.onInk : colors.onDisabled} />
                        </Pressable44>
                    ) : (
                        stopReply
                    )}
                </View>
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
        paddingTop: 12,
        paddingHorizontal: 12,
        paddingBottom: 10,
        gap: 10,
    },
    cardCompact: {
        flexDirection: 'row',
        flexWrap: 'nowrap',
        alignItems: 'center',
        paddingTop: 8,
        paddingBottom: 8,
        gap: 6,
    },
    chipsCompact: {
        width: '22%',
        flexGrow: 0,
        maxHeight: 36,
    },
    inputCompact: {
        maxHeight: 40,
    },
    chips: {
        flexDirection: 'row',
        flexWrap: 'wrap',
        alignItems: 'flex-start',
        gap: 6,
    },
    input: {
        ...inputReset,
        minHeight: 40,
        maxHeight: 120,
        paddingHorizontal: 6,
        paddingVertical: 0,
        ...type.input,
        color: colors.ink,
        textAlignVertical: 'top',
    },
    toolbarCompact: {
        flexShrink: 1,
        width: '65%',
        gap: 4,
    },
    toolbarCompactGap: {
        gap: 4,
    },
    toolbar: {
        flexDirection: 'row',
        flexWrap: 'wrap',
        alignItems: 'center',
        gap: 6,
    },
    tools: {
        flexBasis: 164,
        flexGrow: 1,
        flexShrink: 1,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 6,
    },
    actions: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'flex-end',
        marginLeft: 'auto',
        gap: 6,
    },
    tool: {
        width: 40,
        height: 40,
        borderRadius: 20,
        alignItems: 'center',
        justifyContent: 'center',
    },
    // The default 6pt hit slop keeps the narrow button at a 44pt target, so it can give the option chips room.
    attach: {
        width: 32,
    },
    chip: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 4,
        flexShrink: 1,
        minWidth: 0,
        height: 32,
        paddingLeft: 10,
        paddingRight: 8,
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.hairline,
    },
    chevron: {
        flexShrink: 0,
    },
    chipFixed: {
        flexShrink: 0,
    },
    chipLabel: {
        flexShrink: 1,
        fontSize: 14,
        lineHeight: 18,
        fontWeight: '600',
        color: colors.ink,
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
        backgroundColor: colors.disabledFill,
    },
    stopSecondary: {
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.background,
    },
    stopSquare: {
        width: 12,
        height: 12,
        borderRadius: 2,
        backgroundColor: colors.onInk,
    },
    stopSquareSecondary: {
        backgroundColor: colors.ink,
    },
}))
