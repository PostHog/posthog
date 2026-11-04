import { type ReactElement, useMemo, useState } from 'react'
import { Text, View } from 'react-native'
import { Gesture, GestureDetector } from 'react-native-gesture-handler'

import { ChevronLeftIcon } from '@/ui/icons/ChevronLeftIcon'
import { ChevronRightIcon } from '@/ui/icons/ChevronRightIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

import {
    addMonths,
    type CalendarPick,
    daySpoken,
    daysInclusive,
    dayTitle,
    monthGrid,
    monthOf,
    monthTitle,
    pickDay,
} from './calendar'

const WEEKDAY_LETTERS = ['S', 'M', 'T', 'W', 'T', 'F', 'S'] as const
const MONTH_SWIPE = 40

interface RangeCalendarProps {
    initial: CalendarPick
    /** Today in the project timezone. Later days cannot be picked. */
    today: string
    onApply: (start: string, end: string) => void
}

export function RangeCalendar({ initial, today, onApply }: RangeCalendarProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const [pick, setPick] = useState<CalendarPick>(initial)
    const [month, setMonth] = useState(() => monthOf(initial.end ?? today))
    const lastMonth = monthOf(today)
    const canNext = month < lastMonth
    const grid = useMemo(() => monthGrid(month), [month])

    const showMonth = (count: -1 | 1): void => {
        const next = addMonths(month, count)
        if (next <= lastMonth) {
            setMonth(next)
        }
    }
    const swipe = Gesture.Pan()
        .runOnJS(true)
        .activeOffsetX([-16, 16])
        .failOffsetY([-12, 12])
        .onEnd((event) => {
            if (Math.abs(event.translationX) > MONTH_SWIPE) {
                showMonth(event.translationX > 0 ? -1 : 1)
            }
        })

    const choosingEnd = Boolean(pick.start && !pick.end)
    const ready = Boolean(pick.start && pick.end)

    return (
        <View style={styles.body} testID="range-calendar">
            <View style={styles.fields}>
                <DateField label="Start" value={pick.start} active={!choosingEnd} />
                <Text style={styles.arrow} importantForAccessibility="no" accessibilityElementsHidden>
                    →
                </Text>
                <DateField
                    label="End"
                    value={pick.end}
                    active={choosingEnd}
                    placeholder={pick.start ? undefined : ''}
                />
            </View>
            <Text style={styles.hint} accessibilityLiveRegion="polite" accessibilityRole="text">
                {pickHint(pick)}
            </Text>
            <GestureDetector gesture={swipe}>
                <View style={styles.box}>
                    <View style={styles.nav}>
                        <MonthButton direction={-1} enabled onPress={() => showMonth(-1)} />
                        <Text style={styles.month} accessibilityRole="header">
                            {monthTitle(month)}
                        </Text>
                        <MonthButton direction={1} enabled={canNext} onPress={() => showMonth(1)} />
                    </View>
                    <View style={styles.grid}>
                        {WEEKDAY_LETTERS.map((letter, index) => (
                            <Text
                                // biome-ignore lint/suspicious/noArrayIndexKey: two weekdays share a letter.
                                key={index}
                                style={styles.weekday}
                                importantForAccessibility="no"
                                accessibilityElementsHidden
                            >
                                {letter}
                            </Text>
                        ))}
                        {Array.from({ length: grid.lead }, (_, index) => (
                            // biome-ignore lint/suspicious/noArrayIndexKey: blank cells have no identity.
                            <View key={`lead-${index}`} style={styles.cell} />
                        ))}
                        {grid.days.map((day) => (
                            <DayCell
                                key={day}
                                day={day}
                                pick={pick}
                                today={today}
                                onPress={() => setPick((current) => pickDay(current, day))}
                            />
                        ))}
                    </View>
                </View>
            </GestureDetector>
            <Pressable44
                onPress={() => {
                    if (pick.start && pick.end) {
                        onApply(pick.start, pick.end)
                    }
                }}
                disabled={!ready}
                accessibilityState={{ disabled: !ready }}
                style={[styles.apply, !ready && styles.applyDisabled]}
                pressedBackground={colors.inkHover}
                testID="range-apply"
            >
                <Text style={[styles.applyText, !ready && styles.applyTextDisabled]}>Apply</Text>
            </Pressable44>
        </View>
    )
}

function pickHint({ start, end }: CalendarPick): string {
    if (!start) {
        return 'Tap a start date.'
    }
    if (!end) {
        return 'Now tap an end date.'
    }
    const days = daysInclusive(start, end)
    return `${days === 1 ? '1 day' : `${days} days`} selected. Tap a date to start over.`
}

function DateField({
    label,
    value,
    active,
    placeholder = 'Pick a date',
}: {
    label: string
    value: string | null
    active: boolean
    placeholder?: string
}): ReactElement {
    const styles = useStyles()
    return (
        <View
            style={[styles.field, active && styles.fieldActive]}
            accessible
            accessibilityLabel={`${label}: ${value ? daySpoken(value) : 'not picked'}`}
        >
            <Text style={styles.fieldLabel}>{label}</Text>
            <Text style={styles.fieldValue} numberOfLines={1}>
                {value ? dayTitle(value) : placeholder || ' '}
            </Text>
        </View>
    )
}

function MonthButton({
    direction,
    enabled,
    onPress,
}: {
    direction: -1 | 1
    enabled: boolean
    onPress: () => void
}): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const Icon = direction < 0 ? ChevronLeftIcon : ChevronRightIcon
    return (
        <Pressable44
            onPress={onPress}
            disabled={!enabled}
            accessibilityLabel={direction < 0 ? 'Previous month' : 'Next month'}
            accessibilityState={{ disabled: !enabled }}
            pressedBackground={colors.pressed}
            style={[styles.monthButton, !enabled && styles.monthButtonDisabled]}
            testID={direction < 0 ? 'range-month-prev' : 'range-month-next'}
        >
            <Icon size={13} color={enabled ? colors.ink : colors.disabled} />
        </Pressable44>
    )
}

interface DayCellProps {
    day: string
    pick: CalendarPick
    today: string
    onPress: () => void
}

function DayCell({ day, pick, today, onPress }: DayCellProps): ReactElement {
    const styles = useStyles()
    const { start, end } = pick
    const isStart = day === start
    const isEnd = day === end
    const inside = Boolean(start && end && day > start && day < end)
    const future = day > today
    const banded = Boolean(start && end && start !== end)
    return (
        <Pressable44
            onPress={onPress}
            disabled={future}
            hitSlop={0}
            accessibilityLabel={daySpoken(day)}
            accessibilityState={{ selected: isStart || isEnd, disabled: future }}
            style={styles.cell}
            testID={`range-day-${day}`}
        >
            {inside ? <View style={[styles.band, styles.bandFull]} /> : null}
            {banded && isStart ? <View style={[styles.band, styles.bandRight]} /> : null}
            {banded && isEnd ? <View style={[styles.band, styles.bandLeft]} /> : null}
            <View
                style={[
                    styles.dayCircle,
                    day === today && !isStart && !isEnd && styles.today,
                    (isStart || isEnd) && styles.selected,
                ]}
            >
                <Text style={[styles.dayText, future && styles.dayFuture, (isStart || isEnd) && styles.daySelected]}>
                    {Number(day.slice(8))}
                </Text>
            </View>
        </Pressable44>
    )
}

const CELL_HEIGHT = 42
const CIRCLE = 38

const useStyles = createStyles(({ colors }) => ({
    body: {
        gap: 14,
    },
    fields: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
    },
    arrow: {
        ...type.body,
        color: colors.tertiary,
    },
    field: {
        flex: 1,
        minWidth: 0,
        paddingVertical: 8,
        paddingHorizontal: 12,
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
    },
    fieldActive: {
        borderColor: colors.ink,
        borderWidth: 2,
        paddingVertical: 7,
        paddingHorizontal: 11,
    },
    fieldLabel: {
        ...type.meta,
        color: colors.tertiary,
    },
    fieldValue: {
        ...type.buttonSmall,
        color: colors.ink,
    },
    hint: {
        ...type.meta,
        color: colors.tertiary,
        marginHorizontal: 4,
        marginTop: -4,
    },
    box: {
        paddingTop: 8,
        paddingHorizontal: 8,
        paddingBottom: 10,
        borderRadius: radii.option,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
    },
    nav: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        marginBottom: 6,
    },
    month: {
        ...type.bodyStrong,
        fontWeight: '700',
        color: colors.ink,
    },
    monthButton: {
        width: 40,
        height: 40,
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
        alignItems: 'center',
        justifyContent: 'center',
    },
    monthButtonDisabled: {
        borderColor: colors.hairline,
    },
    grid: {
        flexDirection: 'row',
        flexWrap: 'wrap',
        rowGap: 2,
    },
    weekday: {
        width: `${100 / 7}%`,
        textAlign: 'center',
        fontSize: 12,
        fontWeight: '600',
        color: colors.tertiary,
        paddingTop: 2,
        paddingBottom: 6,
    },
    cell: {
        width: `${100 / 7}%`,
        height: CELL_HEIGHT,
        alignItems: 'center',
        justifyContent: 'center',
    },
    band: {
        position: 'absolute',
        top: (CELL_HEIGHT - CIRCLE) / 2,
        bottom: (CELL_HEIGHT - CIRCLE) / 2,
        backgroundColor: colors.blueHighlight,
    },
    bandFull: {
        left: 0,
        right: 0,
    },
    bandRight: {
        left: '50%',
        right: 0,
    },
    bandLeft: {
        left: 0,
        right: '50%',
    },
    dayCircle: {
        width: CIRCLE,
        height: CIRCLE,
        borderRadius: CIRCLE / 2,
        alignItems: 'center',
        justifyContent: 'center',
    },
    today: {
        borderWidth: 1.5,
        borderColor: colors.border,
    },
    selected: {
        backgroundColor: colors.ink,
    },
    dayText: {
        fontSize: 16,
        color: colors.ink,
        fontVariant: ['tabular-nums'],
    },
    dayFuture: {
        color: colors.disabled,
    },
    daySelected: {
        color: colors.onInk,
        fontWeight: '700',
    },
    apply: {
        height: 50,
        borderRadius: radii.option,
        backgroundColor: colors.ink,
        alignItems: 'center',
        justifyContent: 'center',
    },
    applyDisabled: {
        backgroundColor: colors.disabledFill,
    },
    applyTextDisabled: {
        color: colors.onDisabled,
    },
    applyText: {
        ...type.button,
        color: colors.onInk,
    },
}))
