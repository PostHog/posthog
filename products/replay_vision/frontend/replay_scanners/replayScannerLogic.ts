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
    visionScannersCreate,
    visionScannersDestroy,
    visionScannersObservationsList,
    visionScannersPartialUpdate,
    visionScannersRetrieve,
} from '../generated/api'
import type { ReplayObservationApi } from '../generated/api.schemas'
import { scheduleObservationPoll } from '../logics/observationPolling'
import type { replayScannerLogicType } from './replayScannerLogicType'
import {
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    ScannerConfig,
    ScannerType,
    ReplayScanner,
    scannerFromApi,
    scannerToApiBody,
    scannerToPatchedApiBody,
} from './types'

export interface ReplayScannerLogicProps {
    id: string
    tabId: string
}

function defaultConfigForType(scannerType: ScannerType): ScannerConfig {
    if (scannerType === 'summarizer') {
        return { prompt: '', length: 'medium' }
    }
    if (scannerType === 'classifier') {
        return { prompt: '', tags: [], multi_label: true }
    }
    if (scannerType === 'scorer') {
        return { prompt: '', scale: { min: 0, max: 10 } }
    }
    return { prompt: '' }
}

function omitQuery(scanner: ReplayScanner): Omit<ReplayScanner, 'query'> {
    const { query: _query, ...rest } = scanner
    return rest
}

function newScanner(): ReplayScanner {
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
        scanner_version: 1,
        last_swept_at: dayjs().toISOString(),
        created_at: dayjs().toISOString(),
        updated_at: dayjs().toISOString(),
        created_by: null,
        scanner_type: 'monitor',
        scanner_config: { prompt: '' },
    }
}

export const replayScannerLogic = kea<replayScannerLogicType>([
    path(['products', 'replay_vision', 'frontend', 'replay_scanners', 'replayScannerLogic']),
    props({} as ReplayScannerLogicProps),
    key((props) => `${props.tabId}:${props.id}`),

    actions({
        loadScanner: true,
        loadScannerSuccess: (scanner: ReplayScanner) => ({ scanner }),
        loadScannerFailure: true,
        setScannerType: (scannerType: ScannerType) => ({ scannerType }),
        loadObservations: true,
        loadObservationsSuccess: (observations: ReplayObservationApi[]) => ({ observations }),
        loadObservationsFailure: true,
        deleteScanner: true,
    }),

    forms(({ props }) => ({
        scanner: {
            defaults: newScanner(),
            errors: (scanner: ReplayScanner) => {
                const configErrors: Record<string, string | undefined> = {}
                if (!scanner.scanner_config?.prompt?.trim()) {
                    configErrors.prompt = 'Prompt is required'
                }
                if (scanner.scanner_type === 'scorer') {
                    const { min, max } = scanner.scanner_config.scale
                    if (typeof min !== 'number' || typeof max !== 'number' || min >= max) {
                        configErrors.scale = 'Scale max must be greater than min'
                    }
                }
                return {
                    name: !scanner.name?.trim() ? 'Name is required' : undefined,
                    sampling_rate:
                        scanner.sampling_rate > 0 && scanner.sampling_rate <= 1
                            ? undefined
                            : 'Sampling rate must be between 0% and 100%',
                    scanner_config: Object.keys(configErrors).length > 0 ? configErrors : undefined,
                }
            },
            submit: async (scanner: ReplayScanner) => {
                const teamId = teamLogic.values.currentTeamId
                if (!teamId) {
                    return
                }
                const body = scanner.query == null ? omitQuery(scanner) : scanner
                try {
                    if (props.id === 'new') {
                        const response = await visionScannersCreate(String(teamId), scannerToApiBody(body))
                        router.actions.replace(urls.replayVision(response.id))
                        lemonToast.success('Scanner created')
                    } else {
                        await visionScannersPartialUpdate(String(teamId), props.id, scannerToPatchedApiBody(body))
                        lemonToast.success('Scanner saved')
                    }
                } catch (error) {
                    lemonToast.error(`Failed to save scanner: ${String(error)}`)
                    throw error
                }
            },
        },
    })),

    reducers({
        originalScanner: [
            null as ReplayScanner | null,
            {
                loadScannerSuccess: (_, { scanner }) => scanner,
                submitScannerSuccess: (_, { scanner }: { scanner: ReplayScanner }) => scanner,
            },
        ],
        scannerLoading: [
            false,
            {
                loadScanner: () => true,
                loadScannerSuccess: () => false,
                loadScannerFailure: () => false,
            },
        ],
        observations: [
            [] as ReplayObservationApi[],
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
            (s) => [s.scanner, s.originalScanner],
            (scanner: ReplayScanner | null, original: ReplayScanner | null): boolean => {
                if (!scanner || !original) {
                    return false
                }
                return !objectsEqual(scanner, original)
            },
        ],
        hasObservationsInFlight: [
            (s) => [s.observations],
            (observations: ReplayObservationApi[]): boolean =>
                observations.some((o) => o.status === 'pending' || o.status === 'running'),
        ],
    }),

    listeners(({ actions, props, values, cache }) => ({
        loadScanner: async () => {
            if (props.id === 'new') {
                actions.loadScannerSuccess(newScanner())
                return
            }
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                return
            }
            try {
                const response = await visionScannersRetrieve(String(teamId), props.id)
                actions.loadScannerSuccess(scannerFromApi(response))
            } catch (error) {
                lemonToast.error(`Failed to load scanner: ${String(error)}`)
                actions.loadScannerFailure()
                router.actions.replace(urls.replayVision())
            }
        },

        loadScannerSuccess: ({ scanner }) => {
            actions.setScannerValues(scanner)
        },

        setScannerType: ({ scannerType }) => {
            actions.setScannerValues({ scanner_type: scannerType, scanner_config: defaultConfigForType(scannerType) })
        },

        deleteScanner: async () => {
            if (props.id === 'new') {
                return
            }
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                return
            }
            try {
                await visionScannersDestroy(String(teamId), props.id)
                lemonToast.success('Scanner deleted')
                router.actions.replace(urls.replayVision())
            } catch (error) {
                lemonToast.error(`Failed to delete scanner: ${String(error)}`)
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
                const response = await visionScannersObservationsList(String(teamId), props.id)
                actions.loadObservationsSuccess(response.results ?? [])
            } catch {
                actions.loadObservationsFailure()
            }
        },

        loadObservationsSuccess: () => {
            scheduleObservationPoll(cache.disposables, values.hasObservationsInFlight, actions.loadObservations)
        },
    })),

    afterMount(({ actions, props }) => {
        actions.loadScanner()
        if (props.id !== 'new') {
            actions.loadObservations()
        }
    }),
])
