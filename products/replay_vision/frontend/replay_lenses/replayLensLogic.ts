import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { objectsEqual } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { RecordingsQuery } from '~/queries/schema/schema-general'

import type { replayLensLogicType } from './replayLensLogicType'
import { DEFAULT_MODEL, DEFAULT_PROVIDER, LensConfig, LensType, ReplayLens, ReplayObservation } from './types'

export interface ReplayLensLogicProps {
    id: string
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

function newLens(): ReplayLens {
    return {
        id: 'new',
        name: '',
        description: '',
        enabled: true,
        sampling_rate: 1,
        query: null,
        provider: DEFAULT_PROVIDER,
        model: DEFAULT_MODEL,
        emits_signals: false,
        lens_version: 1,
        last_swept_at: new Date().toISOString(),
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        created_by: null,
        lens_type: 'monitor',
        lens_config: { prompt: '' },
    }
}

export const replayLensLogic = kea<replayLensLogicType>([
    path(['products', 'replay_vision', 'frontend', 'replay_lenses', 'replayLensLogic']),
    props({} as ReplayLensLogicProps),
    key((props) => props.id),

    actions({
        loadLens: true,
        loadLensSuccess: (lens: ReplayLens) => ({ lens }),
        loadLensFailure: true,
        setLens: (lens: ReplayLens) => ({ lens }),
        setName: (name: string) => ({ name }),
        setDescription: (description: string) => ({ description }),
        setLensType: (lensType: LensType) => ({ lensType }),
        setLensConfig: (config: LensConfig) => ({ config }),
        setSamplingRate: (rate: number) => ({ rate }),
        setQuery: (query: RecordingsQuery | null) => ({ query }),
        setModel: (model: string) => ({ model }),
        setEmitsSignals: (emits: boolean) => ({ emits }),
        saveLens: true,
        saveLensSuccess: (lens: ReplayLens) => ({ lens }),
        saveLensFailure: true,
        resetLens: true,
        loadObservations: true,
        loadObservationsSuccess: (observations: ReplayObservation[]) => ({ observations }),
        loadObservationsFailure: true,
    }),

    reducers({
        lens: [
            null as ReplayLens | null,
            {
                loadLensSuccess: (_, { lens }) => lens,
                setLens: (_, { lens }) => lens,
                saveLensSuccess: (_, { lens }) => lens,
                setName: (state, { name }) => (state ? { ...state, name } : state),
                setDescription: (state, { description }) => (state ? { ...state, description } : state),
                setSamplingRate: (state, { rate }) => (state ? { ...state, sampling_rate: rate } : state),
                setQuery: (state, { query }) => (state ? { ...state, query } : state),
                setModel: (state, { model }) => (state ? { ...state, model } : state),
                setEmitsSignals: (state, { emits }) => (state ? { ...state, emits_signals: emits } : state),
                setLensType: (state, { lensType }) => {
                    if (!state) {
                        return state
                    }
                    return { ...state, lens_type: lensType, lens_config: defaultConfigForType(lensType) } as ReplayLens
                },
                setLensConfig: (state, { config }) =>
                    state ? ({ ...state, lens_config: config } as ReplayLens) : state,
            },
        ],
        originalLens: [
            null as ReplayLens | null,
            {
                loadLensSuccess: (_, { lens }) => lens,
                saveLensSuccess: (_, { lens }) => lens,
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
        lensSubmitting: [
            false,
            {
                saveLens: () => true,
                saveLensSuccess: () => false,
                saveLensFailure: () => false,
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
        observationsLoaded: [
            false,
            {
                loadObservationsSuccess: () => true,
                loadLensSuccess: () => false,
            },
        ],
    }),

    selectors({
        isNew: [(_, p) => [p.id], (id: string) => id === 'new'],
        formValid: [
            (s) => [s.lens],
            (lens: ReplayLens | null): boolean => {
                if (!lens) {
                    return false
                }
                if (lens.name.trim().length === 0) {
                    return false
                }
                if (!lens.lens_config?.prompt || lens.lens_config.prompt.trim().length === 0) {
                    return false
                }
                return lens.sampling_rate > 0 && lens.sampling_rate <= 1
            },
        ],
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

    listeners(({ actions, values, props }) => ({
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
                // nosemgrep: prefer-codegen-api
                const response = await api.get(`/api/environments/${teamId}/vision/lenses/${props.id}/`)
                actions.loadLensSuccess(response)
            } catch (error) {
                lemonToast.error(`Failed to load lens: ${String(error)}`)
                actions.loadLensFailure()
            }
        },

        saveLens: async () => {
            const teamId = teamLogic.values.currentTeamId
            const lens = values.lens
            if (!teamId || !lens) {
                return
            }
            try {
                if (props.id === 'new') {
                    // nosemgrep: prefer-codegen-api
                    const response = await api.create(`/api/environments/${teamId}/vision/lenses/`, lens)
                    actions.saveLensSuccess(response)
                    router.actions.replace(urls.replayLens(response.id))
                    lemonToast.success('Lens created')
                } else {
                    // nosemgrep: prefer-codegen-api
                    const response = await api.update(`/api/environments/${teamId}/vision/lenses/${props.id}/`, lens)
                    actions.saveLensSuccess(response)
                    lemonToast.success('Lens saved')
                }
            } catch (error) {
                lemonToast.error(`Failed to save lens: ${String(error)}`)
                actions.saveLensFailure()
            }
        },

        resetLens: () => {
            if (values.originalLens) {
                actions.setLens(values.originalLens)
            } else if (props.id === 'new') {
                actions.setLens(newLens())
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
                // nosemgrep: prefer-codegen-api
                const response = await api.get(`/api/environments/${teamId}/vision/lenses/${props.id}/observations/`)
                actions.loadObservationsSuccess(response.results ?? [])
            } catch {
                actions.loadObservationsFailure()
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadLens()
    }),
])
