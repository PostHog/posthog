import { useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { lemonToast } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { accessLevelSatisfied } from 'lib/utils/accessControlUtils'
import { addProductIntentForCrossSell } from 'lib/utils/product-intents'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType, Experiment } from '~/types'

import { CONCLUSION_DISPLAY_CONFIG } from 'products/experiments/frontend/constants'
import { experimentsMatchingIdsRetrieve } from 'products/experiments/frontend/generated/api'
import type { ExperimentsMatchingIdsRetrieveParams } from 'products/experiments/frontend/generated/api.schemas'
import { experimentsLogic } from 'products/experiments/frontend/scenes/experimentsLogic'

export const EXPERIMENTS_TABLE_EMPTY = 'No results for this filter, change filter or create a new experiment.'
export const LEGACY_EXPERIMENT_TOOLTIP =
    'This experiment uses the legacy engine, so its results are no longer available.'
export const LEGACY_EXPERIMENT_DOCS = 'https://posthog.com/docs/experiments/new-experimentation-engine'

export const getExperimentDuration = (experiment: Experiment): number | undefined => {
    return experiment.end_date
        ? dayjs(experiment.end_date).diff(dayjs(experiment.start_date), 'day')
        : experiment.start_date
          ? dayjs().diff(dayjs(experiment.start_date), 'day')
          : undefined
}

export const formatExperimentDuration = (experiment: Experiment): string => {
    const duration = getExperimentDuration(experiment)
    return duration !== undefined ? `${duration} day${duration !== 1 ? 's' : ''}` : '—'
}

export interface ExperimentRemainingTime {
    state: 'unknown' | 'done' | 'running'
    percent: number
    tooltip: string
}

export function getExperimentRemainingTime(experiment: Experiment): ExperimentRemainingTime {
    const remainingDays = experiment.running_time_calculation?.recommended_running_time
    const daysElapsed = experiment.start_date ? dayjs().diff(dayjs(experiment.start_date), 'day') : undefined

    // A negative stored estimate isn't a real duration, so read it as "no estimate"
    // rather than "~-N days remaining" (records saved before the persist guard can still hold one).
    if (remainingDays === undefined || remainingDays === null || remainingDays < 0) {
        return {
            state: 'unknown',
            percent: 0,
            tooltip: 'Remaining time will be calculated once the experiment has enough data',
        }
    }

    if (remainingDays === 0) {
        return { state: 'done', percent: 100, tooltip: 'Recommended sample size reached' }
    }

    const totalEstimatedDays = (daysElapsed ?? 0) + remainingDays
    const days = Math.ceil(remainingDays)
    return {
        state: 'running',
        percent: totalEstimatedDays > 0 ? ((daysElapsed ?? 0) / totalEstimatedDays) * 100 : 0,
        tooltip: `~${days} day${days !== 1 ? 's' : ''} remaining`,
    }
}

export function getExperimentConclusionTooltip(experiment: Experiment): string | null {
    if (!experiment.conclusion) {
        return null
    }
    const config = CONCLUSION_DISPLAY_CONFIG[experiment.conclusion]
    return experiment.conclusion_comment
        ? `${config.description} — ${experiment.conclusion_comment}`
        : config.description
}

export function experimentSelectionDisabledReason(experiment: Experiment): string | null {
    if (typeof experiment.id !== 'number') {
        return 'This experiment has not been saved yet.'
    }
    return !experiment.user_access_level ||
        accessLevelSatisfied(
            AccessControlResourceType.Experiment,
            experiment.user_access_level,
            AccessControlLevel.Editor
        )
        ? null
        : "You don't have permission to edit this experiment."
}

export function duplicateExperimentDisabledReason(experiment: Experiment): string | undefined {
    return experiment.is_legacy
        ? 'Not supported for experiments using legacy metrics. Please recreate the experiment manually.'
        : undefined
}

export function copyExperimentDisabledReason(experiment: Experiment): string | undefined {
    return experiment.is_legacy ? 'Copying is not supported for experiments using legacy metrics.' : undefined
}

export function startExperimentSurvey(experiment: Experiment, openSurveyModal: (experiment: Experiment) => void): void {
    openSurveyModal(experiment)
    void addProductIntentForCrossSell({
        from: ProductKey.EXPERIMENTS,
        to: ProductKey.SURVEYS,
        intent_context: ProductIntentContext.QUICK_SURVEY_STARTED,
    })
}

export interface MatchingExperimentIds {
    matchingExperimentIds: readonly number[] | null
    matchingExperimentIdsLoading: boolean
    filterIdentity: string
    selectAllMatching: (onIds: (ids: readonly number[]) => void) => Promise<void>
    clearMatchingExperimentIds: () => void
}

/** The "select all matching experiments" request, shared by the bulk selection of both tables. */
export function useMatchingExperimentIds(): MatchingExperimentIds {
    const { currentProjectId, filters } = useValues(experimentsLogic)
    const [matchingExperimentIds, setMatchingExperimentIds] = useState<readonly number[] | null>(null)
    const [matchingExperimentIdsLoading, setMatchingExperimentIdsLoading] = useState(false)

    // Changing a filter changes which experiments the bulk bar refers to, so drop the selection and
    // any cached "all matching" IDs. Page is excluded: selections deliberately span pages.
    const { page: _page, ...filtersWithoutPage } = filters
    const filterIdentity = JSON.stringify(filtersWithoutPage)
    // Ref mirror so an in-flight matching_ids response can detect it raced a filter change.
    const filterIdentityRef = useRef(filterIdentity)
    filterIdentityRef.current = filterIdentity
    useEffect(() => {
        setMatchingExperimentIds(null)
    }, [filterIdentity])

    const selectAllMatching = async (onIds: (ids: readonly number[]) => void): Promise<void> => {
        const requestedFilterIdentity = filterIdentityRef.current
        setMatchingExperimentIdsLoading(true)
        try {
            const response = await experimentsMatchingIdsRetrieve(String(currentProjectId), {
                search: filters.search,
                status: filters.status as ExperimentsMatchingIdsRetrieveParams['status'],
                archived: filters.archived,
                order: filters.order,
                created_by_id: filters.created_by_id?.length ? JSON.stringify(filters.created_by_id) : undefined,
                tags: filters.tags?.length ? JSON.stringify(filters.tags) : undefined,
                excluded_tags: filters.excluded_tags?.length ? JSON.stringify(filters.excluded_tags) : undefined,
            })
            // Drop a response that raced a filter change; the reset effect
            // already cleared the selection it belonged to.
            if (filterIdentityRef.current !== requestedFilterIdentity) {
                return
            }
            setMatchingExperimentIds(response.ids)
            onIds(response.ids)
        } catch {
            lemonToast.error("Couldn't select all matching experiments. Please try again.")
        } finally {
            setMatchingExperimentIdsLoading(false)
        }
    }

    return {
        matchingExperimentIds,
        matchingExperimentIdsLoading,
        filterIdentity,
        selectAllMatching,
        clearMatchingExperimentIds: () => setMatchingExperimentIds(null),
    }
}
