import {
    isMultipleBreakdownType,
    isURLNormalizeable,
} from 'scenes/insights/filters/BreakdownFilter/taxonomicBreakdownFilterUtils'

import type { Breakdown, BreakdownFilter } from '~/queries/schema/schema-general'
import { PropertyType } from '~/types'

import type { PickedProperty } from './PropertyPickerPopover'

const DEFAULT_HISTOGRAM_BIN_COUNT = 10

const CLEARED_SINGLE_BREAKDOWN: BreakdownFilter = {
    breakdown: undefined,
    breakdown_type: undefined,
    breakdown_histogram_bin_count: undefined,
    breakdown_normalize_url: undefined,
    breakdown_group_type_index: undefined,
}

export interface PropertyPickerPreviousBreakdown {
    value: string | number
    type: string
}

function isNumerical(picked: PickedProperty): boolean {
    // The backend marks $session_duration as numerical, but its property type is Duration.
    return (
        picked.propertyType === PropertyType.Numeric ||
        (picked.type === 'session' && picked.propertyType === PropertyType.Duration)
    )
}

export function propertyPickerBreakdownFilter(
    breakdownFilter: BreakdownFilter | null | undefined,
    picked: PickedProperty,
    previous: PropertyPickerPreviousBreakdown | null,
    isTrends: boolean
): BreakdownFilter | null {
    const current = breakdownFilter ?? {}
    const isHistogramable = isTrends && isNumerical(picked)
    const isNormalizeable = isURLNormalizeable(picked.key)

    if (
        current.breakdowns?.some((saved) => saved.property === picked.key && saved.type === picked.type) ||
        (current.breakdown === picked.key && current.breakdown_type === picked.type) ||
        (previous?.value === picked.key && previous.type === picked.type)
    ) {
        return null
    }

    if (!isTrends) {
        return {
            breakdowns: undefined,
            breakdown: picked.key,
            breakdown_type: picked.type,
            breakdown_group_type_index: picked.groupTypeIndex,
            breakdown_histogram_bin_count: undefined,
            breakdown_normalize_url: isNormalizeable ? true : undefined,
        }
    }

    const added: Breakdown = {
        property: picked.key,
        type: picked.type,
        group_type_index: picked.groupTypeIndex,
        histogram_bin_count: isHistogramable ? DEFAULT_HISTOGRAM_BIN_COUNT : undefined,
        normalize_url: isNormalizeable ? true : undefined,
    }

    if (previous) {
        if (!current.breakdowns) {
            return { ...CLEARED_SINGLE_BREAKDOWN, breakdowns: [added] }
        }
        return {
            breakdowns: current.breakdowns.map((saved) =>
                saved.property === previous.value && (saved.type ?? 'event') === previous.type
                    ? {
                          ...saved,
                          ...added,
                          histogram_bin_count: isHistogramable
                              ? saved.histogram_bin_count || DEFAULT_HISTOGRAM_BIN_COUNT
                              : undefined,
                          normalize_url: isNormalizeable ? (saved.normalize_url ?? true) : undefined,
                      }
                    : saved
            ),
        }
    }

    const single =
        current.breakdown_type && current.breakdown && isMultipleBreakdownType(current.breakdown_type)
            ? [
                  {
                      property: current.breakdown as string,
                      type: current.breakdown_type,
                      group_type_index: current.breakdown_group_type_index,
                      histogram_bin_count: current.breakdown_histogram_bin_count,
                      normalize_url: current.breakdown_normalize_url,
                  },
              ]
            : []
    return { ...CLEARED_SINGLE_BREAKDOWN, breakdowns: [...single, ...(current.breakdowns ?? []), added] }
}
