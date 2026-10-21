import { type ReactElement, useEffect, useMemo, useRef, useState } from 'react'
import { ActivityIndicator, ScrollView, Text, TextInput, useWindowDimensions, View } from 'react-native'
import { Gesture, GestureDetector } from 'react-native-gesture-handler'
import { useReanimatedKeyboardAnimation } from 'react-native-keyboard-controller'
import Animated, { useAnimatedStyle } from 'react-native-reanimated'

import { actionErrorMessage } from '@/lib/errors'
import { VERDICT_NOTE_MAX_LENGTH } from '@/model/verdictReasons'
import { BottomSheet } from '@/ui/BottomSheet'
import { CheckIcon } from '@/ui/icons/CheckIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useTheme } from '@/ui/theme'
import { iconSizes, inputReset, radii, type } from '@/ui/tokens'

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
    const { height } = useWindowDimensions()
    const keyboard = useReanimatedKeyboardAnimation()
    const scroll = useRef<ScrollView>(null)
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

    // The sheet lifts with the keyboard, and the list gives up the keyboard's height so the button stays on screen.
    const keyboardStyle = useAnimatedStyle(() => ({ paddingBottom: Math.max(-keyboard.height.value, 0) }))
    const listStyle = useAnimatedStyle(() => ({ maxHeight: Math.max(height * 0.5 + keyboard.height.value, 120) }))

    const canConfirm = reason !== undefined && !pending
    const confirm = (): void => {
        if (reason === undefined || pending) {
            return
        }
        setError(undefined)
        onConfirm(reason, note).catch((confirmError: unknown) => setError(actionErrorMessage(confirmError)))
    }

    return (
        <BottomSheet
            visible={visible}
            onClose={onClose}
            paddingHorizontal={20}
            scrollGesture={listGesture}
            accessibilityLabel={copy.title}
            testID={testID}
        >
            <Animated.View style={keyboardStyle}>
                <Text style={styles.title} accessibilityRole="header" numberOfLines={3}>
                    {copy.title}
                </Text>
                <Text style={styles.description}>{copy.description}</Text>
                {error ? (
                    <Text style={styles.error} accessibilityRole="alert" testID={`${testID}-error`}>
                        {error}
                    </Text>
                ) : null}
                <Animated.View style={[styles.list, listStyle]}>
                    <GestureDetector gesture={listGesture}>
                        <ScrollView ref={scroll} keyboardShouldPersistTaps="handled" style={styles.scroll}>
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
                                value={note}
                                onChangeText={setNote}
                                onFocus={() => scroll.current?.scrollToEnd({ animated: true })}
                                editable={!pending}
                                multiline
                                maxLength={VERDICT_NOTE_MAX_LENGTH}
                                placeholder={copy.notePlaceholder}
                                placeholderTextColor={colors.tertiary}
                                keyboardAppearance={scheme}
                                textAlignVertical="top"
                                style={styles.note}
                                accessibilityLabel="Note"
                                testID={`${testID}-note`}
                            />
                        </ScrollView>
                    </GestureDetector>
                </Animated.View>
                <Pressable44
                    onPress={confirm}
                    disabled={!canConfirm}
                    accessibilityState={{ disabled: !canConfirm, busy: pending }}
                    pressedBackground={colors.inkHover}
                    style={[
                        styles.confirm,
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
            </Animated.View>
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
    error: {
        ...type.metaSmall,
        color: colors.orange,
        marginTop: 6,
        paddingHorizontal: 4,
    },
    list: {
        marginTop: 12,
    },
    scroll: {
        flexGrow: 0,
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
