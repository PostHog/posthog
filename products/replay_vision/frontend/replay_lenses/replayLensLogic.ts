import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { router } from 'kea-router'

import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { objectsEqual } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { NodeKind } from '~/queries/schema/schema-general'

import {
    visionLensesCreate,
    visionLensesDestroy,
    visionLensesObservationsList,
    visionLensesPartialUpdate,
    visionLensesRetrieve,
} from '../generated/api'
import type { replayLensLogicType } from './replayLensLogicType'
import {
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    LensConfig,
    LensType,
    ReplayLens,
    ReplayObservation,
    lensFromApi,
    lensToApiBody,
    lensToPatchedApiBody,
    observationsFromApi,
} from './types'

export interface ReplayLensLogicProps {
    id: string
    tabId: string
}

function defaultConfigForType(lensType: LensType): LensConfig {
    if (lensType === 'summarizer') {
        return { prompt: '', length: 'medium' }
    }
    if (lensType === 'classifier') {
        return { prompt: '', tags: [], multi_label: true }
    }
    if (lensType === 'scorer') {
        return { prompt: '', scale: { min: 0, max: 10 } }
    }
    return { prompt: '' }
}

function omitQuery(lens: ReplayLens): Omit<ReplayLens, 'query'> {
    const { query: _query, ...rest } = lens
    return rest
}

function newLens(): ReplayLens {
    return {
        id: 'new',
        name: '',
        description: '',
        enabled: true,
        sampling_rate: 1,
        query: { kind: NodeKind.RecordingsQuery },
        provider: DEFAULT_PROVIDER,
        model: DEFAULT_MODEL,
        emits_signals: false,
        lens_version: 1,
        last_swept_at: dayjs().toISOString(),
        created_at: dayjs().toISOString(),
        updated_at: dayjs().toISOString(),
        created_by: null,
        lens_type: 'monitor',
        lens_config: { prompt: '' },
    }
}

export const replayLensLogic = kea<replayLensLogicType>([
    path(['products', 'replay_vision', 'frontend', 'replay_lenses', 'replayLensLogic']),
    props({} as ReplayLensLogicProps),
    key((props) => `${props.tabId}:${props.id}`),

    actions({
        loadLens: true,
        loadLensSuccess: (lens: ReplayLens) => ({ lens }),
        loadLensFailure: true,
        setLensType: (lensType: LensType) => ({ lensType }),
        loadObservations: true,
        loadObservationsSuccess: (observations: ReplayObservation[]) => ({ observations }),
        loadObservationsFailure: true,
        deleteLens: true,
    }),

    forms(({ props }) => ({
        lens: {
            defaults: newLens(),
            errors: (lens: ReplayLens) => {
                const configErrors: Record<string, string | undefined> = {}
                if (!lens.lens_config?.prompt?.trim()) {
                    configErrors.prompt = 'Prompt is required'
                }
                if (lens.lens_type === 'scorer') {
                    const { min, max } = lens.lens_config.scale
                    if (typeof min !== 'number' || typeof max !== 'number' || min >= max) {
                        configErrors.scale = 'Scale max must be greater than min'
                    }
                }
                return {
                    name: !lens.name?.trim() ? 'Name is required' : undefined,
                    sampling_rate:
                        lens.sampling_rate > 0 && lens.sampling_rate <= 1
                            ? undefined
                            : 'Sampling rate must be between 0% and 100%',
                    lens_config: Object.keys(configErrors).length > 0 ? configErrors : undefined,
                }
            },
            submit: async (lens: ReplayLens) => {
                const teamId = teamLogic.values.currentTeamId
                if (!teamId) {
                    return
                }
                const body = lens.query == null ? omitQuery(lens) : lens
                try {
                    if (props.id === 'new') {
                        const response = await visionLensesCreate(String(teamId), lensToApiBody(body))
                        router.actions.replace(urls.replayVision(response.id))
                        lemonToast.success('Lens created')
                    } else {
                        await visionLensesPartialUpdate(String(teamId), props.id, lensToPatchedApiBody(body))
                        lemonToast.success('Lens saved')
                    }
                } catch (error) {
                    lemonToast.error(`Failed to save lens: ${String(error)}`)
                    throw error
                }
            },
        },
    })),

    reducers({
        originalLens: [
            null as ReplayLens | null,
            {
                loadLensSuccess: (_, { lens }) => lens,
                submitLensSuccess: (_, { lens }: { lens: ReplayLens }) => lens,
            },
        ],
        lensLoading: [
            false,
            {
                loadLens: () => true,
                loadLensSuccess: () => false,
                loadLensFailure: () => false,
            },
        ],
        observations: [
            [] as ReplayObservation[],
            {
                loadObservationsSuccess: (_, { observations }) => observations,
            },
        ],
        observationsLoading: [
            false,
            {
                loadObservations: () => true,
                loadObservationsSuccess: () => false,
                loadObservationsFailure: () => false,
            },
        ],
    }),

    selectors({
        isNew: [(_, p) => [p.id], (id: string) => id === 'new'],
        hasUnsavedChanges: [
            (s) => [s.lens, s.originalLens],
            (lens: ReplayLens | null, original: ReplayLens | null): boolean => {
                if (!lens || !original) {
                    return false
                }
                return !objectsEqual(lens, original)
            },
        ],
    }),

    listeners(({ actions, props }) => ({
        loadLens: async () => {
            if (props.id === 'new') {
                actions.loadLensSuccess(newLens())
                return
            }
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                return
            }
            try {
                const response = await visionLensesRetrieve(String(teamId), props.id)
                actions.loadLensSuccess(lensFromApi(response))
            } catch (error) {
                lemonToast.error(`Failed to load lens: ${String(error)}`)
                actions.loadLensFailure()
                router.actions.replace(urls.replayVision())
            }
        },

        loadLensSuccess: ({ lens }) => {
            actions.setLensValues(lens)
        },

        setLensType: ({ lensType }) => {
            actions.setLensValues({ lens_type: lensType, lens_config: defaultConfigForType(lensType) })
        },

        deleteLens: async () => {
            if (props.id === 'new') {
                return
            }
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                return
            }
            try {
                await visionLensesDestroy(String(teamId), props.id)
                lemonToast.success('Lens deleted')
                router.actions.replace(urls.replayVision())
            } catch (error) {
                lemonToast.error(`Failed to delete lens: ${String(error)}`)
            }
        },

        loadObservations: async () => {
            if (props.id === 'new') {
                actions.loadObservationsSuccess([])
                return
            }
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                return
            }
            try {
                const response = await visionLensesObservationsList(String(teamId), props.id)
                actions.loadObservationsSuccess(observationsFromApi(response.results ?? []))
            } catch {
                actions.loadObservationsFailure()
            }
        },
    })),

    afterMount(({ actions, props }) => {
        actions.loadLens()
        if (props.id !== 'new') {
            actions.loadObservations()
        }
    }),
])
