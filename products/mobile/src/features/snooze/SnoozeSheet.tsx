import { type ReactElement, useEffect, useMemo, useState } from 'react'
import { Text, View } from 'react-native'

import { actionErrorMessage } from '@/lib/errors'
import type { SnoozeChoice } from '@/model/types'
import { BottomSheet } from '@/ui/BottomSheet'
import { ClockIcon } from '@/ui/icons/ClockIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, radii, type } from '@/ui/tokens'

import { CustomSnoozePicker } from './CustomSnoozePicker'
import { formatSnoozeWhen, SNOOZE_SIGNAL_COUNT, snoozeUntil, type TimePreset } from './snoozeTimes'

const TIME_PRESETS: readonly { preset: TimePreset; label: string }[] = [
    { preset: 'hour', label: 'In an hour' },
    { preset: 'tomorrow', label: 'Tomorrow' },
    { preset: 'next_week', label: 'Next week' },
    { preset: 'month', label: 'In a month' },
]

interface SnoozeSheetProps {
    visible: boolean
    onClose: () => void
    /** A rejection keeps the sheet open with the error under the title. */
    onSnooze: (choice: SnoozeChoice) => Promise<void>
    pending: boolean
}

interface RowProps {
    label: string
    sub?: string
    when?: string
    onPress: () => void
    disabled: boolean
    testID: string
}

function SnoozeRow({ label, sub, when, onPress, disabled, testID }: RowProps): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    return (
        <Pressable44
            onPress={onPress}
            disabled={disabled}
            pressedBackground={colors.background}
            style={styles.row}
            testID={testID}
        >
            <ClockIcon size={iconSizes.control} />
            <View style={styles.rowBody}>
                <Text style={styles.label}>{label}</Text>
                {sub ? <Text style={styles.sub}>{sub}</Text> : null}
            </View>
            {when ? <Text style={styles.when}>{when}</Text> : null}
        </Pressable44>
    )
}

export function SnoozeSheet({ visible, onClose, onSnooze, pending }: SnoozeSheetProps): ReactElement {
    const styles = useStyles()
    const [custom, setCustom] = useState(false)
    const [now, setNow] = useState(() => new Date())
    const [error, setError] = useState<string | undefined>(undefined)

    useEffect(() => {
        if (visible) {
            setNow(new Date())
            setCustom(false)
            setError(undefined)
        }
    }, [visible])

    const pick = (choice: SnoozeChoice): void => {
        setError(undefined)
        onSnooze(choice).catch((snoozeError: unknown) => setError(actionErrorMessage(snoozeError)))
    }

    const presets = useMemo(
        () =>
            TIME_PRESETS.map(({ preset, label }) => {
                const until = snoozeUntil(preset, now)
                return { preset, label, until, when: formatSnoozeWhen(preset, until) }
            }),
        [now]
    )

    return (
        <BottomSheet
            visible={visible}
            onClose={onClose}
            paddingHorizontal={20}
            accessibilityLabel="Snooze"
            testID="snooze-sheet"
        >
            <Text style={styles.title}>Snooze</Text>
            {error ? (
                <Text style={styles.error} accessibilityRole="alert" testID="snooze-error">
                    {error}
                </Text>
            ) : null}
            {custom ? (
                <CustomSnoozePicker
                    initial={snoozeUntil('tomorrow', now)}
                    onCancel={() => setCustom(false)}
                    onConfirm={(date) => pick({ kind: 'until', preset: 'custom', until: date.toISOString() })}
                />
            ) : (
                <View style={styles.rows}>
                    <SnoozeRow
                        label="Until more signals arrive"
                        sub={`Hide until ${SNOOZE_SIGNAL_COUNT} more signals`}
                        onPress={() => pick({ kind: 'signals', count: SNOOZE_SIGNAL_COUNT })}
                        disabled={pending}
                        testID="snooze-signals"
                    />
                    {presets.map(({ preset, label, until, when }) => (
                        <SnoozeRow
                            key={preset}
                            label={label}
                            when={when}
                            onPress={() => pick({ kind: 'until', preset, until: until.toISOString() })}
                            disabled={pending}
                            testID={`snooze-${preset}`}
                        />
                    ))}
                    <SnoozeRow
                        label="Custom…"
                        onPress={() => setCustom(true)}
                        disabled={pending}
                        testID="snooze-custom"
                    />
                </View>
            )}
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
    error: {
        ...type.metaSmall,
        color: colors.orange,
        marginTop: 6,
        paddingHorizontal: 4,
    },
    rows: {
        marginTop: 8,
    },
    row: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 14,
        minHeight: 56,
        paddingHorizontal: 4,
        borderRadius: radii.card,
    },
    rowBody: {
        flex: 1,
        minWidth: 0,
    },
    label: {
        ...type.label,
        color: colors.ink,
    },
    sub: {
        ...type.metaSmall,
        color: colors.tertiary,
    },
    when: {
        fontSize: 15,
        lineHeight: 21,
        color: colors.tertiary,
    },
}))
