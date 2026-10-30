import type { ReactElement } from 'react'
import { ActivityIndicator, ScrollView, StyleSheet, Text, useWindowDimensions, View } from 'react-native'
import { GestureDetector, type NativeGesture } from 'react-native-gesture-handler'

import type { ModelChoiceApi, ReasoningEffortApi, ResolvedAiRunDefaultsApi } from '@/api/tasks'
import { Eyebrow } from '@/ui/Eyebrow'
import { CheckIcon } from '@/ui/icons/CheckIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, radii, type } from '@/ui/tokens'

import {
    COST_BASELINE_LABEL,
    catalogueEntry,
    defaultModelSelection,
    EFFORT_LABELS,
    HARNESS_LABELS,
    modelDisplayName,
    type RunOptions,
    runtimeAdapters,
} from './runOptions'
import { SheetPageHeader } from './SheetPageHeader'
import type { ModelCatalogueState } from './useRunOptions'

interface ModelPageProps {
    catalogue: ModelCatalogueState
    defaults: ResolvedAiRunDefaultsApi | undefined
    model: RunOptions['model']
    onPickModel: (option: ModelChoiceApi) => void
    onPickEffort: (effort: ReasoningEffortApi) => void
    onResetModel: () => void
    /** Also passed to the sheet, whose drag-to-close pan waits for it, so a drag on the list scrolls it. */
    listGesture: NativeGesture
    onBack: () => void
}

interface ModelRowProps {
    option: ModelChoiceApi
    selected: boolean
    isDefault: boolean
    onPress: () => void
}

function ModelRow({ option, selected, isDefault, onPress }: ModelRowProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    return (
        <Pressable44
            onPress={onPress}
            accessibilityRole="radio"
            accessibilityLabel={option.display_name}
            accessibilityState={{ checked: selected }}
            pressedBackground={colors.background}
            style={[styles.row, selected && styles.rowSelected]}
            testID={`handoff-model-${option.model}`}
        >
            <Text style={[styles.rowLabel, selected && type.bodyStrong]} numberOfLines={1}>
                {option.display_name}
            </Text>
            {isDefault ? <Text style={[styles.rowMeta, selected && styles.rowMetaSelected]}>Default</Text> : null}
            {option.cost_multiplier ? <Text style={styles.cost}>{option.cost_multiplier}</Text> : null}
            <View style={styles.check}>{selected ? <CheckIcon size={iconSizes.control} /> : null}</View>
        </Pressable44>
    )
}

export function ModelPage({
    catalogue,
    defaults,
    model,
    onPickModel,
    onPickEffort,
    onResetModel,
    listGesture,
    onBack,
}: ModelPageProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const { height: windowHeight } = useWindowDimensions()
    const models = catalogue.catalogue
    const pinned = model === 'default' ? undefined : model
    const fallback = defaultModelSelection(defaults)
    const defaultEntry = catalogueEntry(models, fallback?.model)
    const effortModel = pinned ? catalogueEntry(models, pinned.model) : defaultEntry
    const efforts = effortModel?.supported_efforts ?? []
    // An untouched picker claims an effort only when the default names one; with none the server picks.
    const selectedEffort: ReasoningEffortApi | undefined = pinned
        ? (pinned.reasoningEffort ?? undefined)
        : efforts.find((effort) => effort === fallback?.reasoningEffort)
    const showsCost = models.some((option) => option.cost_multiplier)

    return (
        <View testID="handoff-model-page">
            <SheetPageHeader title="Model and reasoning" onBack={onBack} testID="handoff-model-page" />
            {catalogue.loading ? (
                <ActivityIndicator style={styles.loading} color={colors.ink} />
            ) : catalogue.unavailable ? (
                <Text style={styles.note} testID="handoff-model-unavailable">
                    Couldn't load the model list. The run uses your default model.
                </Text>
            ) : (
                <>
                    {efforts.length > 0 ? (
                        <View style={styles.section}>
                            <Eyebrow>Reasoning</Eyebrow>
                            <View style={styles.efforts} accessibilityRole="radiogroup">
                                {efforts.map((effort) => {
                                    const selected = effort === selectedEffort
                                    return (
                                        <Pressable44
                                            key={effort}
                                            onPress={() => onPickEffort(effort)}
                                            accessibilityRole="radio"
                                            accessibilityState={{ checked: effort === selectedEffort }}
                                            pressedBackground={selected ? colors.inkHover : colors.background}
                                            style={[styles.effort, selected && styles.effortSelected]}
                                            testID={`handoff-effort-${effort}`}
                                        >
                                            <Text style={[styles.effortText, selected && styles.effortTextSelected]}>
                                                {EFFORT_LABELS[effort]}
                                            </Text>
                                        </Pressable44>
                                    )
                                })}
                            </View>
                        </View>
                    ) : null}
                    <GestureDetector gesture={listGesture}>
                        <ScrollView
                            style={[styles.list, { maxHeight: Math.round(windowHeight * 0.42) }]}
                            accessibilityRole="radiogroup"
                        >
                            {runtimeAdapters(models).map((adapter) => (
                                <View key={adapter}>
                                    <View style={styles.harness}>
                                        <Eyebrow>{HARNESS_LABELS[adapter]}</Eyebrow>
                                    </View>
                                    {models
                                        .filter((option) => option.runtime_adapter === adapter)
                                        .map((option) => (
                                            <ModelRow
                                                key={option.model}
                                                option={option}
                                                selected={(pinned?.model ?? defaultEntry?.model) === option.model}
                                                isDefault={
                                                    !pinned && Boolean(fallback) && option.model === defaultEntry?.model
                                                }
                                                onPress={() => onPickModel(option)}
                                            />
                                        ))}
                                </View>
                            ))}
                            {showsCost ? (
                                <Text style={styles.footnote}>× is cost per token vs {COST_BASELINE_LABEL}</Text>
                            ) : null}
                        </ScrollView>
                    </GestureDetector>
                </>
            )}
            {pinned ? (
                <Pressable44
                    onPress={onResetModel}
                    pressedBackground={colors.background}
                    style={styles.reset}
                    testID="handoff-model-reset"
                >
                    <Text style={styles.resetText}>Reset to default</Text>
                    {fallback ? (
                        <Text style={styles.rowMeta} numberOfLines={1}>
                            {modelDisplayName(models, fallback.model)}
                        </Text>
                    ) : null}
                </Pressable44>
            ) : null}
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    loading: {
        paddingVertical: 28,
    },
    note: {
        ...type.metaSmall,
        color: colors.muted,
        paddingHorizontal: 4,
        paddingVertical: 16,
    },
    section: {
        marginTop: 8,
        paddingHorizontal: 4,
        gap: 8,
    },
    efforts: {
        flexDirection: 'row',
        flexWrap: 'wrap',
        gap: 6,
    },
    effort: {
        minHeight: 36,
        paddingHorizontal: 12,
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
        alignItems: 'center',
        justifyContent: 'center',
    },
    effortSelected: {
        borderColor: colors.ink,
        backgroundColor: colors.ink,
    },
    effortText: {
        ...type.metaSmall,
        color: colors.ink,
    },
    effortTextSelected: {
        color: colors.onInk,
        fontWeight: '600',
    },
    list: {
        marginTop: 8,
        flexGrow: 0,
    },
    harness: {
        paddingHorizontal: 4,
        paddingTop: 12,
        paddingBottom: 2,
    },
    row: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 10,
        minHeight: 48,
        paddingHorizontal: 4,
        borderRadius: radii.card,
    },
    rowSelected: {
        backgroundColor: colors.background,
    },
    rowLabel: {
        ...type.body,
        color: colors.ink,
        flex: 1,
        minWidth: 0,
    },
    rowMeta: {
        ...type.meta,
        color: colors.tertiary,
    },
    rowMetaSelected: {
        color: colors.ink,
        fontWeight: '600',
    },
    cost: {
        ...type.meta,
        color: colors.muted,
        fontVariant: ['tabular-nums'],
    },
    check: {
        width: iconSizes.control,
        alignItems: 'center',
    },
    footnote: {
        ...type.meta,
        color: colors.tertiary,
        paddingHorizontal: 4,
        paddingTop: 8,
        paddingBottom: 4,
    },
    reset: {
        marginTop: 8,
        minHeight: 48,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 10,
        paddingHorizontal: 4,
        borderTopWidth: StyleSheet.hairlineWidth,
        borderTopColor: colors.rowDivider,
    },
    resetText: {
        ...type.bodySmallStrong,
        color: colors.ink,
    },
}))
