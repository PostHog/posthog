import { type ReactElement, useEffect, useMemo, useRef, useState } from 'react'
import type { ScrollViewInstance, TextInputInstance } from 'react-native'
import { ActivityIndicator, Text, TextInput, View } from 'react-native'
import { Gesture, GestureDetector } from 'react-native-gesture-handler'
import { useReanimatedKeyboardAnimation } from 'react-native-keyboard-controller'
import Animated from 'react-native-reanimated'
import { actionErrorMessage } from '@/lib/errors'
import { VERDICT_NOTE_MAX_LENGTH } from '@/model/verdictReasons'
import { BottomSheet } from '@/ui/BottomSheet'
import { CheckIcon } from '@/ui/icons/CheckIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useTheme } from '@/ui/theme'
import { iconSizes, inputReset, radii, type } from '@/ui/tokens'
import { useSceneDimensions } from '@/ui/useSceneDimensions'

import type { VerdictCopy } from './verdictCopy'

interface VerdictSheetProps<Reason extends string> {
    visible: boolean
    copy: VerdictCopy
    options: readonly { value: Reason; label: string }[]
    onClose: () => void
    /** A rejection keeps the sheet open with the error under the title. */
    onConfirm: (reason: Reason, note: string) => Promise<void>
    pending: boolean
    testID: string
}

/** The resolve and dismiss sheets: pick a reason, add an optional note, confirm. */
export function VerdictSheet<Reason extends string>({
    visible,
    copy,
    options,
    onClose,
    onConfirm,
    pending,
    testID,
}: VerdictSheetProps<Reason>): ReactElement {
    const styles = useStyles()
    const { colors, scheme } = useTheme()
    const { height } = useSceneDimensions()
    const compact = height < 480
    const keyboard = useReanimatedKeyboardAnimation()
    const scroll = useRef<ScrollViewInstance>(null)
    const noteInput = useRef<TextInputInstance>(null)
    const listGesture = useMemo(() => Gesture.Native(), [])
    const [reason, setReason] = useState<Reason | undefined>(undefined)
    const [note, setNote] = useState('')
    const [error, setError] = useState<string | undefined>(undefined)

    useEffect(() => {
        if (visible) {
            setReason(undefined)
            setNote('')
            setError(undefined)
        }
    }, [visible])

    const canConfirm = reason !== undefined && !pending
    const confirm = (): void => {
        if (reason === undefined || pending) {
            return
        }
        setError(undefined)
        onConfirm(reason, note).catch((confirmError: unknown) => setError(actionErrorMessage(confirmError)))
    }

    const heading = (
        <>
            <Text style={styles.title} accessibilityRole="header" numberOfLines={3}>
                {copy.title}
            </Text>
            <Text style={styles.description}>{copy.description}</Text>
            {error ? (
                <Text style={styles.error} accessibilityRole="alert" testID={`${testID}-error`}>
                    {error}
                </Text>
            ) : null}
        </>
    )

    return (
        <BottomSheet
            visible={visible}
            onClose={onClose}
            paddingHorizontal={20}
            scrollGesture={listGesture}
            keyboardHeight={keyboard.height}
            accessibilityLabel={copy.title}
            testID={testID}
        >
            <View style={styles.content}>
                {compact ? null : heading}
                <View style={[styles.list, compact && { marginTop: 4 }]}>
                    <GestureDetector gesture={listGesture}>
                        <Animated.ScrollView
                            ref={scroll}
                            keyboardShouldPersistTaps="handled"
                            onLayout={() => {
                                if (noteInput.current?.isFocused()) {
                                    scroll.current?.scrollToEnd({ animated: false })
                                }
                            }}
                            style={[styles.scroll, { maxHeight: Math.max(height * 0.5, 120) }]}
                        >
                            {compact ? heading : null}
                            <Text style={styles.fieldLabel}>Reason</Text>
                            <View accessibilityRole="radiogroup">
                                {options.map((option) => {
                                    const selected = option.value === reason
                                    return (
                                        <Pressable44
                                            key={option.value}
                                            onPress={() => setReason(option.value)}
                                            disabled={pending}
                                            accessibilityRole="radio"
                                            accessibilityLabel={option.label}
                                            accessibilityState={{ checked: selected, disabled: pending }}
                                            pressedBackground={colors.background}
                                            style={styles.row}
                                            testID={`${testID}-reason-${option.value}`}
                                        >
                                            <Text style={styles.rowLabel}>{option.label}</Text>
                                            {selected ? <CheckIcon size={iconSizes.control} /> : null}
                                        </Pressable44>
                                    )
                                })}
                            </View>
                            <Text style={[styles.fieldLabel, styles.noteLabel]}>Note</Text>
                            <Text style={styles.noteInfo}>{copy.noteInfo}</Text>
                            <TextInput
                                ref={noteInput}
                                value={note}
                                onChangeText={setNote}
                                onFocus={() => scroll.current?.scrollToEnd({ animated: true })}
                                editable={!pending}
                                multiline
                                disableFullscreenUI
                                maxLength={VERDICT_NOTE_MAX_LENGTH}
                                placeholder={copy.notePlaceholder}
                                placeholderTextColor={colors.tertiary}
                                keyboardAppearance={scheme}
                                textAlignVertical="top"
                                style={[styles.note, compact && styles.noteCompact]}
                                accessibilityLabel="Note"
                                testID={`${testID}-note`}
                            />
                        </Animated.ScrollView>
                    </GestureDetector>
                </View>
                <Pressable44
                    onPress={confirm}
                    disabled={!canConfirm}
                    accessibilityState={{ disabled: !canConfirm, busy: pending }}
                    pressedBackground={colors.inkHover}
                    style={[
                        styles.confirm,
                        compact && { marginTop: 4, height: 44 },
                        { backgroundColor: canConfirm || pending ? colors.ink : colors.disabledFill },
                    ]}
                    testID={`${testID}-confirm`}
                >
                    {pending ? (
                        <ActivityIndicator size="small" color={colors.onInk} />
                    ) : (
                        <Text style={[styles.confirmText, !canConfirm && styles.confirmTextDisabled]}>
                            {copy.submitLabel}
                        </Text>
                    )}
                </Pressable44>
            </View>
        </BottomSheet>
    )
}

const useStyles = createStyles(({ colors }) => ({
    content: {
        flexShrink: 1,
        minHeight: 0,
    },
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
    error: {
        ...type.metaSmall,
        color: colors.orange,
        marginTop: 6,
        paddingHorizontal: 4,
    },
    list: {
        marginTop: 12,
        flexShrink: 1,
        minHeight: 0,
    },
    scroll: {
        flexGrow: 0,
        flexShrink: 1,
    },
    fieldLabel: {
        ...type.bodySmallStrong,
        color: colors.ink,
        paddingHorizontal: 4,
        marginBottom: 2,
    },
    noteLabel: {
        marginTop: 14,
    },
    noteInfo: {
        ...type.meta,
        color: colors.tertiary,
        paddingHorizontal: 4,
        marginBottom: 8,
    },
    row: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 14,
        minHeight: 48,
        paddingHorizontal: 4,
        borderRadius: radii.card,
    },
    rowLabel: {
        ...type.label,
        color: colors.ink,
        flex: 1,
        minWidth: 0,
    },
    note: {
        ...inputReset,
        ...type.input,
        color: colors.ink,
        minHeight: 88,
        paddingHorizontal: 14,
        paddingTop: 12,
        paddingBottom: 12,
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.background,
    },
    noteCompact: {
        height: 44,
        minHeight: 44,
        maxHeight: 44,
        paddingTop: 8,
        paddingBottom: 8,
    },
    confirm: {
        marginTop: 16,
        height: 52,
        borderRadius: radii.pill,
        alignItems: 'center',
        justifyContent: 'center',
    },
    confirmText: {
        ...type.button,
        color: colors.onInk,
    },
    confirmTextDisabled: {
        color: colors.onDisabled,
    },
}))
