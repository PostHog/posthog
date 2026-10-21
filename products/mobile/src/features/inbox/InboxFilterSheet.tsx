import { Fragment, type ReactElement, useMemo } from 'react'
import { ScrollView, StyleSheet, Text, useWindowDimensions, View } from 'react-native'
import { Gesture, GestureDetector } from 'react-native-gesture-handler'

import { FEATURE_FLAGS, useFeatureFlag } from '@/lib/featureFlags'
import type { InboxItem } from '@/model/types'
import { BottomSheet } from '@/ui/BottomSheet'
import { Eyebrow } from '@/ui/Eyebrow'
import { FadeEdge } from '@/ui/FadeEdge'
import { CheckIcon } from '@/ui/icons/CheckIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { SegmentedPill } from '@/ui/SegmentedPill'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, radii, space, type } from '@/ui/tokens'

import {
    CREATED_WINDOW_OPTIONS,
    type CreatedWindow,
    type InboxFilters,
    type InboxSort,
    isDefaultInboxFilters,
    MODEL_SCORE_SORT_OPTION,
    SORT_OPTIONS,
    type SortOption,
    type SourceFilterKey,
    sourceFilterOptionsFor,
} from './filters'

interface InboxFilterSheetProps {
    visible: boolean
    onClose: () => void
    filters: InboxFilters
    /** The loaded reports before the filters, so a selected source never hides the other sources' chips. */
    items: readonly InboxItem[]
    onSortChange: (sort: InboxSort) => void
    onCreatedWindowChange: (window: CreatedWindow) => void
    onToggleSource: (key: SourceFilterKey) => void
    onClear: () => void
}

/** Sort, created window and sources for the inbox. A choice applies at once, so the sheet has no Apply button. */
export function InboxFilterSheet({
    visible,
    onClose,
    filters,
    items,
    onSortChange,
    onCreatedWindowChange,
    onToggleSource,
    onClear,
}: InboxFilterSheetProps): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    const { height } = useWindowDimensions()
    const listGesture = useMemo(() => Gesture.Native(), [])
    const modelScoreSort = useFeatureFlag(FEATURE_FLAGS.modelScoreSort)
    const sortOptions = modelScoreSort ? [...SORT_OPTIONS, MODEL_SCORE_SORT_OPTION] : SORT_OPTIONS
    const sourceOptions = useMemo(() => sourceFilterOptionsFor(items, filters.sources), [items, filters.sources])
    const isDefault = isDefaultInboxFilters(filters)

    return (
        <BottomSheet
            visible={visible}
            onClose={onClose}
            paddingHorizontal={20}
            scrollGesture={listGesture}
            accessibilityLabel="Filter and sort"
            testID="inbox-filter-sheet"
        >
            <View style={styles.head}>
                <Text style={styles.title} accessibilityRole="header">
                    Filter and sort
                </Text>
                <Pressable44
                    onPress={onClear}
                    disabled={isDefault}
                    accessibilityLabel="Clear"
                    accessibilityState={{ disabled: isDefault }}
                    pressedBackground={colors.sunken}
                    style={styles.clear}
                    testID="inbox-filters-clear"
                >
                    <Text style={[styles.clearText, isDefault && styles.clearTextDisabled]}>Clear</Text>
                </Pressable44>
            </View>
            <View>
                <GestureDetector gesture={listGesture}>
                    <ScrollView
                        style={{ maxHeight: Math.round(height * 0.7) }}
                        contentContainerStyle={styles.body}
                        showsVerticalScrollIndicator={false}
                    >
                        <View style={styles.section}>
                            <View style={styles.sectionHead}>
                                <Eyebrow>Sort by</Eyebrow>
                            </View>
                            <View style={styles.card} accessibilityRole="radiogroup">
                                {sortOptions.map((option, index) => (
                                    <Fragment key={option.key}>
                                        {index > 0 ? <View style={styles.divider} /> : null}
                                        <SortRow
                                            option={option}
                                            selected={filters.sort === option.key}
                                            onPress={() => onSortChange(option.key)}
                                        />
                                    </Fragment>
                                ))}
                            </View>
                        </View>
                        <View style={styles.section}>
                            <View style={styles.sectionHead}>
                                <Eyebrow>Created</Eyebrow>
                            </View>
                            <SegmentedPill
                                segments={CREATED_WINDOW_OPTIONS.map((option) => ({
                                    key: option.key,
                                    accessibilityLabel: option.label,
                                    accessibilityRole: 'radio' as const,
                                    selected: filters.createdWindow === option.key,
                                    onPress: () => onCreatedWindowChange(option.key),
                                    testID: `inbox-created-${option.key}`,
                                    children: (
                                        <Text style={styles.segmentText} numberOfLines={1}>
                                            {option.shortLabel}
                                        </Text>
                                    ),
                                }))}
                            />
                        </View>
                        <View style={styles.section}>
                            <View style={styles.sectionHead}>
                                <Eyebrow>Sources</Eyebrow>
                                {sourceOptions.length > 0 ? (
                                    <Text style={styles.hint}>Select any number. None means all sources.</Text>
                                ) : null}
                            </View>
                            {sourceOptions.length === 0 ? (
                                <Text style={styles.none}>No sources yet</Text>
                            ) : (
                                <View style={styles.chips}>
                                    {sourceOptions.map(({ key, label, Icon }) => {
                                        const selected = filters.sources.includes(key)
                                        return (
                                            <Pressable44
                                                key={key}
                                                onPress={() => onToggleSource(key)}
                                                accessibilityRole="checkbox"
                                                accessibilityLabel={label}
                                                accessibilityState={{ checked: selected }}
                                                pressedBackground={colors.pressed}
                                                style={[styles.chip, selected && styles.chipSelected]}
                                                testID={`inbox-source-${key}`}
                                            >
                                                <View style={[styles.checkbox, selected && styles.checkboxSelected]}>
                                                    {selected ? (
                                                        <CheckIcon size={12} color={colors.onInk} strokeWidth={3} />
                                                    ) : null}
                                                </View>
                                                <Icon
                                                    size={iconSizes.small}
                                                    color={selected ? colors.ink : colors.secondary}
                                                />
                                                <Text style={styles.chipText}>{label}</Text>
                                            </Pressable44>
                                        )
                                    })}
                                </View>
                            )}
                        </View>
                    </ScrollView>
                </GestureDetector>
                <View style={styles.fade}>
                    <FadeEdge direction="up" solid={0} color={colors.surface} />
                </View>
            </View>
        </BottomSheet>
    )
}

interface SortRowProps {
    option: SortOption
    selected: boolean
    onPress: () => void
}

function SortRow({ option, selected, onPress }: SortRowProps): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    const { Icon } = option
    return (
        <Pressable44
            onPress={onPress}
            hitSlop={0}
            accessibilityRole="radio"
            accessibilityLabel={option.description ? `${option.label}, ${option.description}` : option.label}
            accessibilityState={{ selected }}
            pressedBackground={colors.pressed}
            style={[styles.row, selected && styles.rowSelected]}
            testID={`inbox-sort-${option.key}`}
        >
            <Icon size={iconSizes.control} color={colors.ink} />
            <View style={styles.rowText}>
                <Text style={styles.rowLabel}>{option.label}</Text>
                {option.description ? <Text style={styles.rowDescription}>{option.description}</Text> : null}
            </View>
            {selected ? <CheckIcon size={iconSizes.control} /> : null}
        </Pressable44>
    )
}

const FADE_HEIGHT = space[24]
const ROW_PADDING = space[16]
const ROW_GAP = space[12]
// Dividers start under the label, past the icon, like a grouped list.
const ROW_TEXT_INSET = ROW_PADDING + iconSizes.control + ROW_GAP

const useStyles = createStyles(({ colors }) => ({
    head: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 12,
        paddingTop: 14,
        paddingBottom: 8,
        paddingHorizontal: 4,
    },
    title: {
        ...type.sheetTitle,
        color: colors.ink,
        flexShrink: 1,
    },
    clear: {
        height: 36,
        paddingHorizontal: 12,
        marginRight: -12,
        borderRadius: radii.pill,
        alignItems: 'center',
        justifyContent: 'center',
    },
    clearText: {
        ...type.buttonSmall,
        color: colors.blue,
    },
    clearTextDisabled: {
        color: colors.disabled,
    },
    body: {
        gap: 18,
        paddingTop: 4,
        paddingBottom: FADE_HEIGHT,
    },
    fade: {
        position: 'absolute',
        left: 0,
        right: 0,
        bottom: 0,
        height: FADE_HEIGHT,
        pointerEvents: 'none',
    },
    section: {
        gap: 8,
    },
    sectionHead: {
        gap: 2,
        paddingHorizontal: 4,
    },
    hint: {
        ...type.meta,
        color: colors.tertiary,
    },
    card: {
        backgroundColor: colors.surface,
        borderWidth: 1,
        borderColor: colors.hairline,
        borderRadius: radii.softCard,
        overflow: 'hidden',
    },
    divider: {
        height: StyleSheet.hairlineWidth,
        marginLeft: ROW_TEXT_INSET,
        backgroundColor: colors.rowDivider,
    },
    row: {
        minHeight: 56,
        paddingVertical: space[8],
        paddingHorizontal: ROW_PADDING,
        flexDirection: 'row',
        alignItems: 'center',
        gap: ROW_GAP,
    },
    rowSelected: {
        backgroundColor: colors.sunken,
    },
    rowText: {
        flex: 1,
        minWidth: 0,
    },
    rowLabel: {
        ...type.body,
        color: colors.ink,
    },
    rowDescription: {
        ...type.meta,
        color: colors.tertiary,
    },
    segmentText: {
        ...type.buttonSmall,
        color: colors.ink,
    },
    chips: {
        flexDirection: 'row',
        flexWrap: 'wrap',
        gap: 8,
    },
    chip: {
        height: 36,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 6,
        paddingLeft: 10,
        paddingRight: 14,
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
    },
    chipSelected: {
        backgroundColor: colors.sunken,
        borderColor: colors.ink,
    },
    chipText: {
        ...type.buttonSmall,
        color: colors.ink,
    },
    checkbox: {
        width: iconSizes.inline,
        height: iconSizes.inline,
        marginRight: 2,
        borderRadius: 4,
        borderWidth: 1.5,
        borderColor: colors.control,
        alignItems: 'center',
        justifyContent: 'center',
    },
    checkboxSelected: {
        backgroundColor: colors.ink,
        borderColor: colors.ink,
    },
    none: {
        ...type.meta,
        color: colors.tertiary,
        paddingHorizontal: 4,
    },
}))
