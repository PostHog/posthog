import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

import { PersonalAPIKeyType } from '~/types'

import type { sourceMapsFixWizardLogicType } from './sourceMapsFixWizardLogicType'
import { SOURCE_MAPS_TECHNOLOGIES, Technology, TechnologyKey, getTechnology } from './sourceMapsTechnologies'

export type WizardStep = 1 | 2 | 3 | 4

const SOURCE_MAP_UPLOAD_SCOPES = ['organization:read', 'error_tracking:write']
const SETUP_CHECK_WINDOW_MINUTES = 15

export type SetupCheck = {
    since_minutes: number
    symbol_sets: { id: string; ref: string; created_at: string; has_uploaded_file: boolean }[]
    frames: { total: number; resolved: number; unresolved: number }
}

export const sourceMapsFixWizardLogic = kea<sourceMapsFixWizardLogicType>([
    path(['products', 'error_tracking', 'scenes', 'ErrorTrackingScene', 'tabs', 'recommendations', 'fixWizard']),

    connect(() => ({
        values: [teamLogic, ['currentTeam']],
    })),

    actions({
        setStep: (step: WizardStep) => ({ step }),
        nextStep: true,
        prevStep: true,
        setSelectedTechKey: (key: TechnologyKey) => ({ key }),
        setPromptRevealed: (revealed: boolean) => ({ revealed }),
        createApiKey: true,
        createApiKeySuccess: (key: PersonalAPIKeyType) => ({ key }),
        createApiKeyFailure: (error: string) => ({ error }),
        reset: true,
    }),

    reducers({
        currentStep: [
            1 as WizardStep,
            {
                setStep: (_, { step }) => step,
                reset: () => 1,
            },
        ],
        selectedTechKey: [
            'auto' as TechnologyKey,
            {
                setSelectedTechKey: (_, { key }) => key,
                reset: () => 'auto',
            },
        ],
        promptRevealed: [
            false,
            {
                setPromptRevealed: (_, { revealed }) => revealed,
                setSelectedTechKey: () => false,
                reset: () => false,
            },
        ],
        createdApiKey: [
            null as PersonalAPIKeyType | null,
            {
                createApiKeySuccess: (_, { key }) => key,
                reset: () => null,
            },
        ],
        isCreatingApiKey: [
            false,
            {
                createApiKey: () => true,
                createApiKeySuccess: () => false,
                createApiKeyFailure: () => false,
                reset: () => false,
            },
        ],
        apiKeyError: [
            null as string | null,
            {
                createApiKey: () => null,
                createApiKeyFailure: (_, { error }) => error,
                reset: () => null,
            },
        ],
    }),

    loaders({
        setupCheck: [
            null as SetupCheck | null,
            {
                loadSetupCheck: async () => {
                    return await api.errorTracking.sourceMapsSetupCheck({ sinceMinutes: SETUP_CHECK_WINDOW_MINUTES })
                },
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        nextStep: () => {
            const next = Math.min(4, values.currentStep + 1) as WizardStep
            actions.setStep(next)
        },
        prevStep: () => {
            const prev = Math.max(1, values.currentStep - 1) as WizardStep
            actions.setStep(prev)
        },
        setStep: ({ step }) => {
            if (step === 4) {
                actions.loadSetupCheck()
            }
        },
        createApiKey: async () => {
            try {
                const key = await api.personalApiKeys.create({
                    label: `Source map upload — ${new Date().toLocaleDateString()}`,
                    scopes: SOURCE_MAP_UPLOAD_SCOPES,
                    scoped_organizations: [],
                    scoped_teams: [],
                })
                actions.createApiKeySuccess(key)
                lemonToast.success('Personal API key created')
            } catch (e: any) {
                const detail = e?.data?.detail ?? e?.message ?? 'Something went wrong creating the personal API key.'
                actions.createApiKeyFailure(detail)
                lemonToast.error(detail)
            }
        },
    })),

    selectors({
        technologies: [() => [], (): Technology[] => SOURCE_MAPS_TECHNOLOGIES],
        selectedTechnology: [(s) => [s.selectedTechKey], (key): Technology => getTechnology(key)],
        host: [() => [], (): string => apiHostOrigin()],
        projectId: [(s) => [s.currentTeam], (currentTeam): number | string => currentTeam?.id ?? 'your-project-id'],
        prompt: [
            (s) => [s.selectedTechnology, s.host, s.projectId],
            (technology, host, projectId): string => technology.buildPrompt({ host, projectId }),
        ],
    }),
])
