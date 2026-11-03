import { type ReactElement, useEffect, useMemo, useState } from 'react'
import {
    AccessibilityInfo,
    Platform,
    ScrollView,
    StyleSheet,
    Switch,
    Text,
    useWindowDimensions,
    View,
} from 'react-native'
import { Gesture, GestureDetector } from 'react-native-gesture-handler'

import type { RangePresetKey } from '@/model/views'
import { BottomSheet } from '@/ui/BottomSheet'
import { CheckIcon } from '@/ui/icons/CheckIcon'
import { ChevronLeftIcon } from '@/ui/icons/ChevronLeftIcon'
import { ChevronRightIcon } from '@/ui/icons/ChevronRightIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

import { CHIP_PRESETS, customRange, formatRangeSpanForSpeech, MORE_PRESETS, RANGE_PRESETS } from '../rangePresets'
import type { ViewRange } from '../rangeStore'
import { SheetTitle } from '../screen/SheetTitle'
import type { CalendarPick } from './calendar'
import { RangeCalendar } from './RangeCalendar'

export interface RangeCompareRow {
    on: boolean
    /** False draws the switch disabled, with `note` under the title. */
    enabled: boolean
    note: string
    onChange: (on: boolean) => void
}

interface RangeSheetProps {
    visible: boolean
    onClose: () => void
    range: ViewRange
    /** What the header shows when the range has no label: a dashboard whose tiles keep their own ranges. */
    emptyLabel: string
    /** The resolved dates on screen, such as "Oct 8 – 14". */
    detail: string | null
    /** Today in the project timezone. */
    today: string
    /** Null leaves the row out, as on web analytics, which always compares. */
    compare: RangeCompareRow | null
}

type Page = 'main' | 'custom'

/** Quick chips, the web's other presets, a custom calendar, compare and reset. Chips and presets apply at once. */
export function RangeSheet({
    visible,
    onClose,
    range,
    emptyLabel,
    detail,
    today,
    compare,
}: RangeSheetProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const [page, setPage] = useState<Page>('main')
    const { height } = useWindowDimensions()
    const listGesture = useMemo(() => Gesture.Native(), [])
    useEffect(() => {
        if (visible) {
            setPage('main')
        }
    }, [visible])

    const choose = (key: RangePresetKey, method: 'chip' | 'more'): void => {
        if (range.preset !== key) {
            range.setChoice({ kind: 'preset', key }, method)
        }
    }
    const applyCustom = (start: string, end: string): void => {
        range.setChoice(customRange(start, end), 'custom')
        onClose()
        AccessibilityInfo.announceForAccessibility(`Showing ${formatRangeSpanForSpeech(start, end)}`)
    }

    return (
        <BottomSheet
            visible={visible}
            onClose={onClose}
            scrollGesture={listGesture}
            backgroundColor={colors.background}
            accessibilityLabel={page === 'main' ? 'Date range' : 'Custom range'}
            testID="range-sheet"
        >
            {page === 'main' ? (
                <SheetTitle title="Date range" onDone={onClose} />
            ) : (
                <CustomHead onBack={() => setPage('main')} />
            )}
            <GestureDetector gesture={listGesture}>
                <ScrollView
                    style={{ maxHeight: Math.round(height * 0.74) }}
                    contentContainerStyle={styles.body}
                    showsVerticalScrollIndicator={false}
                >
                    {page === 'main' ? (
                        <MainPage
                            range={range}
                            emptyLabel={emptyLabel}
                            detail={detail}
                            compare={compare}
                            onChoose={choose}
                            onCustom={() => setPage('custom')}
                        />
                    ) : (
                        <RangeCalendar initial={calendarStart(range)} today={today} onApply={applyCustom} />
                    )}
                </ScrollView>
            </GestureDetector>
        </BottomSheet>
    )
}

function calendarStart(range: ViewRange): CalendarPick {
    const { choice } = range
    if (choice?.kind === 'fixed' && !choice.explicitDate) {
        return { start: choice.dateFrom, end: choice.dateTo }
    }
    return { start: null, end: null }
}

interface MainPageProps {
    range: ViewRange
    emptyLabel: string
    detail: string | null
    compare: RangeCompareRow | null
    onChoose: (key: RangePresetKey, method: 'chip' | 'more') => void
    onCustom: () => void
}

function MainPage({ range, emptyLabel, detail, compare, onChoose, onCustom }: MainPageProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const fixed = range.choice?.kind === 'fixed'
    return (
        <>
            <View style={styles.showing} accessible accessibilityLabel={`Showing ${range.label ?? emptyLabel}`}>
                <Text style={styles.meta}>Showing</Text>
                <Text style={styles.showingValue}>{range.label ?? emptyLabel}</Text>
                {detail ? <Text style={styles.meta}>{detail}</Text> : null}
            </View>
            <View style={styles.chips} accessibilityLabel="Quick ranges">
                {CHIP_PRESETS.map((key) => {
                    const selected = range.preset === key
                    return (
                        <Pressable44
                            key={key}
                            onPress={() => onChoose(key, 'chip')}
                            accessibilityLabel={RANGE_PRESETS[key].label}
                            accessibilityState={{ selected }}
                            pressedBackground={selected ? undefined : colors.pressed}
                            style={[styles.chip, selected && styles.chipSelected]}
                            testID={`range-chip-${key}`}
                        >
                            <Text style={[styles.chipText, selected && styles.chipTextSelected]} numberOfLines={1}>
                                {RANGE_PRESETS[key].chipLabel}
                            </Text>
                        </Pressable44>
                    )
                })}
            </View>
            <View style={styles.group}>
                {MORE_PRESETS.map((key, index) => (
                    <OptionRow
                        key={key}
                        label={RANGE_PRESETS[key].label}
                        selected={range.preset === key}
                        first={index === 0}
                        onPress={() => onChoose(key, 'more')}
                        testID={`range-preset-${key}`}
                    />
                ))}
                <OptionRow
                    label="Custom range"
                    selected={fixed}
                    first={false}
                    meta={fixed && range.label ? range.label : 'Pick dates'}
                    chevron
                    onPress={onCustom}
                    testID="range-custom"
                />
            </View>
            {compare ? <CompareRow compare={compare} /> : null}
            {range.isSaved ? null : (
                <Pressable44
                    onPress={range.reset}
                    pressedBackground={colors.pressed}
                    style={styles.reset}
                    testID="range-reset"
                >
                    <Text style={styles.resetText}>Reset to saved range</Text>
                    <Text style={styles.meta} numberOfLines={1}>
                        {range.savedLabel ?? emptyLabel}
                    </Text>
                </Pressable44>
            )}
        </>
    )
}

interface OptionRowProps {
    label: string
    selected: boolean
    first: boolean
    meta?: string
    chevron?: boolean
    onPress: () => void
    testID: string
}

function OptionRow({ label, selected, first, meta, chevron = false, onPress, testID }: OptionRowProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    return (
        <Pressable44
            onPress={onPress}
            hitSlop={0}
            accessibilityState={{ selected }}
            accessibilityLabel={meta ? `${label}, ${meta}` : label}
            pressedBackground={colors.pressed}
            style={[styles.option, !first && styles.optionDivider]}
            testID={testID}
        >
            <View style={styles.check}>{selected ? <CheckIcon size={16} color={colors.blue} /> : null}</View>
            <Text style={styles.optionText} numberOfLines={1}>
                {label}
            </Text>
            {meta ? (
                <Text style={styles.meta} numberOfLines={1}>
                    {meta}
                </Text>
            ) : null}
            {chevron ? <ChevronRightIcon size={12} color={colors.tertiary} /> : null}
        </Pressable44>
    )
}

function CompareRow({ compare }: { compare: RangeCompareRow }): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    // The sheet draws through a portal, so new props arrive one render after the switch's own change event. A
    // controlled switch that still sees the old value in that render turns itself back, so the row keeps the value.
    const [on, setOn] = useState(compare.on)
    useEffect(() => {
        setOn(compare.on)
    }, [compare.on])
    const change = (next: boolean): void => {
        setOn(next)
        compare.onChange(next)
    }
    const webSwitchProps = Platform.OS === 'web' ? { activeThumbColor: colors.white } : {}
    return (
        <View style={styles.toggleRow}>
            <View style={styles.grow}>
                <Text style={[styles.toggleTitle, !compare.enabled && styles.toggleTitleDisabled]}>
                    Compare to previous period
                </Text>
                <Text style={styles.meta}>{compare.note}</Text>
            </View>
            <Switch
                {...webSwitchProps}
                value={on}
                onValueChange={change}
                disabled={!compare.enabled}
                trackColor={{ true: colors.blue, false: colors.switchOff }}
                thumbColor={colors.white}
                accessibilityLabel="Compare to previous period"
                accessibilityHint={compare.enabled ? undefined : compare.note}
                testID="range-compare"
            />
        </View>
    )
}

function CustomHead({ onBack }: { onBack: () => void }): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    return (
        <View style={styles.customHead}>
            <Pressable44
                onPress={onBack}
                accessibilityLabel="Back"
                pressedBackground={colors.sunken}
                style={styles.back}
                testID="range-custom-back"
            >
                <ChevronLeftIcon size={13} color={colors.blue} />
                <Text style={styles.backText}>Back</Text>
            </Pressable44>
            <Text style={styles.customTitle} accessibilityRole="header">
                Custom range
            </Text>
            <View style={styles.backSpacer} />
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    body: {
        gap: 14,
        paddingTop: 2,
        paddingBottom: 8,
    },
    meta: {
        ...type.meta,
        color: colors.tertiary,
        flexShrink: 1,
    },
    showing: {
        paddingHorizontal: 4,
        gap: 1,
    },
    showingValue: {
        fontSize: 17,
        lineHeight: 22,
        fontWeight: '700',
        color: colors.ink,
    },
    chips: {
        flexDirection: 'row',
        flexWrap: 'wrap',
        gap: 8,
    },
    chip: {
        flexBasis: '30%',
        flexGrow: 1,
        height: 40,
        paddingHorizontal: 10,
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
        alignItems: 'center',
        justifyContent: 'center',
    },
    chipSelected: {
        backgroundColor: colors.ink,
        borderColor: colors.ink,
    },
    chipText: {
        ...type.buttonSmall,
        color: colors.ink,
    },
    chipTextSelected: {
        color: colors.onInk,
    },
    group: {
        borderRadius: radii.option,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
        overflow: 'hidden',
    },
    option: {
        minHeight: 48,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 10,
        paddingHorizontal: 14,
        backgroundColor: colors.surface,
    },
    optionDivider: {
        borderTopWidth: StyleSheet.hairlineWidth,
        borderTopColor: colors.rowDivider,
    },
    check: {
        width: 18,
        alignItems: 'center',
    },
    optionText: {
        ...type.body,
        color: colors.ink,
        flex: 1,
    },
    toggleRow: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        paddingVertical: 12,
        paddingHorizontal: 14,
        borderRadius: radii.option,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
    },
    grow: {
        flex: 1,
        minWidth: 0,
    },
    toggleTitle: {
        ...type.bodyStrong,
        color: colors.ink,
    },
    toggleTitleDisabled: {
        color: colors.secondary,
    },
    reset: {
        minHeight: 48,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 10,
        paddingHorizontal: 14,
        borderRadius: radii.option,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
    },
    resetText: {
        ...type.bodyStrong,
        color: colors.ink,
    },
    customHead: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        paddingTop: 10,
        paddingBottom: 12,
    },
    back: {
        height: 36,
        minWidth: 72,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 4,
        paddingLeft: 6,
        paddingRight: 12,
        borderRadius: radii.pill,
    },
    backText: {
        ...type.bodyStrong,
        color: colors.blue,
    },
    customTitle: {
        ...type.sheetTitleLarge,
        color: colors.ink,
    },
    backSpacer: {
        width: 72,
    },
}))
