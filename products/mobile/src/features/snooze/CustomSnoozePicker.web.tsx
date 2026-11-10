import { type ReactElement, useState } from 'react'
import { Text, TextInput, View } from 'react-native'

import { formatClock, formatMonthDay } from '@/lib/dates'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useTheme } from '@/ui/theme'
import { inputReset, radii, type } from '@/ui/tokens'

import type { CustomSnoozePickerProps } from './CustomSnoozePicker'
import { parseCustomSnooze } from './snoozeTimes'

function pad(value: number): string {
    return String(value).padStart(2, '0')
}

function toInputValue(date: Date): string {
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

/** The web build has no native picker, so "Custom…" takes a typed date and time. */
export function CustomSnoozePicker({ initial, onConfirm, onCancel }: CustomSnoozePickerProps): ReactElement {
    const styles = useStyles()
    const { colors, scheme } = useTheme()
    const [text, setText] = useState(() => toInputValue(initial))
    const parsed = parseCustomSnooze(text, new Date())
    return (
        <View style={styles.container}>
            <TextInput
                value={text}
                onChangeText={setText}
                placeholder="2026-10-10 09:00"
                placeholderTextColor={colors.tertiary}
                keyboardAppearance={scheme}
                style={styles.input}
                accessibilityLabel="Snooze until, as year-month-day hour:minute"
                autoFocus
            />
            <Text style={styles.hint}>
                {parsed
                    ? `Snoozes until ${formatMonthDay(parsed)} at ${formatClock(parsed)}`
                    : 'Enter a future time as year-month-day and a 24-hour time.'}
            </Text>
            <View style={styles.buttons}>
                <Pressable44
                    onPress={onCancel}
                    style={[styles.button, styles.secondary]}
                    pressedBackground={colors.pressed}
                >
                    <Text style={styles.secondaryText}>Back</Text>
                </Pressable44>
                <Pressable44
                    onPress={() => parsed && onConfirm(parsed)}
                    disabled={!parsed}
                    style={[styles.button, styles.primary, !parsed && styles.disabled]}
                    pressedBackground={colors.inkHover}
                >
                    <Text style={[styles.primaryText, !parsed && styles.disabledText]}>Snooze</Text>
                </Pressable44>
            </View>
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    container: {
        marginTop: 8,
        gap: 10,
    },
    input: {
        ...inputReset,
        height: 48,
        borderRadius: radii.card,
        backgroundColor: colors.sunken,
        paddingHorizontal: 16,
        ...type.input,
        color: colors.ink,
    },
    hint: {
        ...type.metaSmall,
        color: colors.tertiary,
        paddingHorizontal: 4,
    },
    buttons: {
        flexDirection: 'row',
        gap: 8,
    },
    button: {
        flex: 1,
        height: 46,
        borderRadius: radii.option,
        alignItems: 'center',
        justifyContent: 'center',
    },
    secondary: {
        backgroundColor: colors.background,
    },
    secondaryText: {
        ...type.buttonSmall,
        color: colors.ink,
    },
    primary: {
        backgroundColor: colors.ink,
    },
    disabled: {
        backgroundColor: colors.disabledFill,
    },
    disabledText: {
        color: colors.onDisabled,
    },
    primaryText: {
        ...type.buttonSmall,
        color: colors.onInk,
    },
}))
