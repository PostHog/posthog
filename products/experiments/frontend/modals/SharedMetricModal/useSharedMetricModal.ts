import { useActions, useValues } from 'kea'

import { pluralize } from 'lib/utils/strings'
import { SharedMetric } from 'scenes/experiments/SharedMetrics/sharedMetricLogic'
import { sharedMetricsLogic } from 'scenes/experiments/SharedMetrics/sharedMetricsLogic'

import { Experiment } from '~/types'

import { MetricContext } from 'products/experiments/frontend/modals/ExperimentMetricModal/experimentMetricModalLogic'

import { sharedMetricModalLogic } from './sharedMetricModalLogic'

export const NO_COMPATIBLE_SHARED_METRICS =
    "You don't have any shared metrics that match the experiment type. Shared metrics let you create reusable metrics that you can quickly add to any experiment."

export interface SharedMetricModalModel {
    ready: boolean
    isOpen: boolean
    close: () => void
    save: () => void
    saveLabel: string
    saveDisabledReason?: string
    hasAnyCompatibleSharedMetrics: boolean
    alreadyAddedNote: string | null
    alreadyAddedIds: Set<number>
    displayedMetrics: SharedMetric[]
    displayedSelectableIds: number[]
    selectedMetricIds: number[]
    setSelectedMetricIds: (ids: number[]) => void
    toggleSelectedMetricId: (id: number) => void
    clearSelectedMetricIds: () => void
    selectAllDisplayed: () => void
    searchTerm: string
    setSearchTerm: (term: string) => void
    availableTags: string[]
    filterTags: string[]
    selectByTag: (tag: string) => void
    clearFilterTags: () => void
    loading: boolean
    savingTagsMetricId: number | null
    updateSharedMetricTags: (id: number, tags: string[]) => void
}

export function useSharedMetricModal(
    experiment: Experiment,
    onSave: (metrics: SharedMetric[], context: MetricContext) => void
): SharedMetricModalModel {
    const {
        isModalOpen,
        context,
        compatibleSharedMetrics,
        displayedMetrics,
        availableTags,
        filterTags,
        searchTerm,
        sharedMetricsResponseLoading,
        hasAnyCompatibleSharedMetrics,
        selectedMetricIds,
    } = useValues(sharedMetricModalLogic)
    const {
        closeSharedMetricModal,
        setSearchTerm,
        toggleSelectedMetricId,
        setSelectedMetricIds,
        clearSelectedMetricIds,
        selectByTag,
        clearFilterTags,
    } = useActions(sharedMetricModalLogic)
    const { savingTagsMetricId } = useValues(sharedMetricsLogic)
    const { updateSharedMetricTags } = useActions(sharedMetricsLogic)

    const savedMetrics = experiment.saved_metrics ?? []
    const alreadyAddedIdsList = savedMetrics.map((savedMetric) => savedMetric.saved_metric)
    const alreadyAddedIds = new Set(alreadyAddedIdsList)
    // Ids of the currently displayed metrics (after tag filtering) that can still be added.
    const displayedSelectableIds = displayedMetrics
        .filter((metric: SharedMetric) => !alreadyAddedIds.has(metric.id))
        .map((metric: SharedMetric) => metric.id)

    const close = (): void => {
        clearSelectedMetricIds()
        closeSharedMetricModal()
    }

    return {
        ready: !!compatibleSharedMetrics,
        isOpen: isModalOpen,
        close,
        save: () => {
            const metrics = selectedMetricIds
                .map((metricId) => compatibleSharedMetrics?.find((m) => m.id === metricId))
                .filter((metric): metric is SharedMetric => metric !== undefined)
            onSave(metrics, context)
            clearSelectedMetricIds()
        },
        saveLabel: selectedMetricIds.length < 2 ? 'Add metric' : 'Add metrics',
        saveDisabledReason: selectedMetricIds.length === 0 ? 'Please select at least one metric' : undefined,
        hasAnyCompatibleSharedMetrics,
        alreadyAddedNote:
            savedMetrics.length > 0
                ? `${pluralize(savedMetrics.length, 'shared metric')} ${savedMetrics.length > 1 ? 'are' : 'is'} already in the experiment.`
                : null,
        alreadyAddedIds,
        displayedMetrics,
        displayedSelectableIds,
        selectedMetricIds,
        setSelectedMetricIds,
        toggleSelectedMetricId,
        clearSelectedMetricIds,
        // Add every currently displayed (tag-filtered) metric to the selection.
        selectAllDisplayed: () =>
            setSelectedMetricIds(Array.from(new Set([...selectedMetricIds, ...displayedSelectableIds]))),
        searchTerm,
        setSearchTerm,
        availableTags,
        filterTags,
        // Toggle this tag: selects (and shows) every metric carrying it, across all pages, or deselects them if it was already active.
        selectByTag: (tag) => selectByTag(tag, alreadyAddedIdsList),
        clearFilterTags,
        loading: sharedMetricsResponseLoading,
        savingTagsMetricId,
        updateSharedMetricTags,
    }
}
