import DateTimePicker, { DateTimePickerAndroid, type DateTimePickerEvent } from '@react-native-community/datetimepicker'
import { type ReactElement, useState } from 'react'
import { Platform, Text, View } from 'react-native'

import { formatClock, formatMonthDay } from '@/lib/dates'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

export interface CustomSnoozePickerProps {
    initial: Date
    onConfirm: (date: Date) => void
    onCancel: () => void
}

/** Native date and time picker for "Custom…". iOS shows wheels inline; Android opens its dialogs. */
export function CustomSnoozePicker({ initial, onConfirm, onCancel }: CustomSnoozePickerProps): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    const [value, setValue] = useState(initial)
    const now = new Date()

    const openAndroid = (): void => {
        DateTimePickerAndroid.open({
            value,
            mode: 'date',
            minimumDate: now,
            onChange: (event: DateTimePickerEvent, date?: Date) => {
                if (event.type !== 'set' || !date) {
                    return
                }
                DateTimePickerAndroid.open({
                    value: date,
                    mode: 'time',
                    onChange: (timeEvent: DateTimePickerEvent, time?: Date) => {
                        if (timeEvent.type === 'set' && time) {
                            setValue(time)
                        }
                    },
                })
            },
        })
    }

    return (
        <View style={styles.container}>
            {Platform.OS === 'ios' ? (
                <DateTimePicker
                    value={value}
                    mode="datetime"
                    display="spinner"
                    minimumDate={now}
                    onChange={(_event: DateTimePickerEvent, date?: Date) => date && setValue(date)}
                />
            ) : (
                <Pressable44 onPress={openAndroid} style={styles.field} pressedBackground={colors.sunken}>
                    <Text style={styles.fieldText}>
                        {formatMonthDay(value)} at {formatClock(value)}
                    </Text>
                </Pressable44>
            )}
            <View style={styles.buttons}>
                <Pressable44
                    onPress={onCancel}
                    style={[styles.button, styles.secondary]}
                    pressedBackground={colors.pressed}
                >
                    <Text style={styles.secondaryText}>Back</Text>
                </Pressable44>
                <Pressable44
                    onPress={() => onConfirm(value)}
                    disabled={value.getTime() <= Date.now()}
                    style={[styles.button, styles.primary]}
                    pressedBackground={colors.inkHover}
                >
                    <Text style={styles.primaryText}>Snooze</Text>
                </Pressable44>
            </View>
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    container: {
        marginTop: 8,
        gap: 12,
    },
    field: {
        height: 48,
        borderRadius: radii.card,
        backgroundColor: colors.sunken,
        justifyContent: 'center',
        paddingHorizontal: 16,
    },
    fieldText: {
        ...type.label,
        color: colors.ink,
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
    primaryText: {
        ...type.buttonSmall,
        color: colors.onInk,
    },
}))
