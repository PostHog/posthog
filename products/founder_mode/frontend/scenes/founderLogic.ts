import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import api from 'lib/api'

import type { founderLogicType } from './founderLogicType'

export type FounderStep = 'ideation' | 'validation' | 'gtm' | 'mvp' | 'marketing'

export const FOUNDER_STEPS: FounderStep[] = ['ideation', 'validation', 'gtm', 'mvp', 'marketing']

export interface SocialPost {
    platform: string
    content: string
    tips: string
}

export interface LaunchStep {
    title: string
    description: string
    channel: string
    timeline: string
    ready_to_use_content: SocialPost[]
}

export interface GTMResult {
    launch_summary: string
    target_communities: string[]
    steps: LaunchStep[]
}

export interface GTMState {
    status: 'pending' | 'running' | 'completed' | 'failed'
    result: GTMResult | null
    error: string
}

interface FounderProjectListItem {
    id: string
    name: string
    current_step: FounderStep
}

const POLL_INTERVAL_MS = 2000
const FOUNDER_PROJECTS_URL = 'api/projects/@current/founder_projects/'

export const founderLogic = kea<founderLogicType>([
    path(['products', 'founder_mode', 'frontend', 'scenes', 'founderLogic']),

    actions({
        setStep: (step: number) => ({ step }),
        setCurrentProjectId: (projectId: string | null) => ({ projectId }),
        setCurrentStep: (currentStep: FounderStep) => ({ currentStep }),
        advanceStep: (currentStep: FounderStep) => ({ currentStep }),
        setProductDescription: (description: string) => ({ description }),
        generateStrategy: true,
        setGtmState: (state: GTMState) => ({ state }),
        loadExistingProject: true,
        loadExistingGtm: true,
        pollGtmStatus: true,
        stopGtmPolling: true,
        setProjectLoaded: (loaded: boolean) => ({ loaded }),
    }),

    reducers({
        step: [
            0,
            {
                setStep: (_, { step }) => step,
            },
        ],
        currentProjectId: [
            null as string | null,
            {
                setCurrentProjectId: (_, { projectId }) => projectId,
            },
        ],
        currentStep: [
            'ideation' as FounderStep,
            {
                setCurrentStep: (_, { currentStep }) => currentStep,
                advanceStep: (_, { currentStep }) => currentStep,
            },
        ],
        projectLoaded: [
            false,
            {
                setProjectLoaded: (_, { loaded }) => loaded,
            },
        ],
        productDescription: [
            '',
            {
                setProductDescription: (_, { description }) => description,
            },
        ],
        gtmState: [
            null as GTMState | null,
            {
                setGtmState: (_, { state }) => state,
                generateStrategy: () => ({ status: 'pending', result: null, error: '' }) as GTMState,
            },
        ],
        gtmPolling: [
            false,
            {
                generateStrategy: () => true,
                stopGtmPolling: () => false,
            },
        ],
    }),

    selectors({
        hasExistingProject: [(s) => [s.currentProjectId], (id): boolean => id !== null],
    }),

    listeners(({ actions, values }) => ({
        loadExistingProject: async () => {
            try {
                const response = await api.get<{ results: FounderProjectListItem[] }>(FOUNDER_PROJECTS_URL)
                const projects = response.results
                if (projects.length > 0) {
                    const latest = projects[0]
                    actions.setCurrentProjectId(latest.id)
                    actions.setCurrentStep(latest.current_step)
                }
            } catch {
                // No existing projects — stay on ideation
            }
            actions.setProjectLoaded(true)
        },

        advanceStep: async ({ currentStep }) => {
            if (!values.currentProjectId) {
                return
            }
            try {
                await api.update(`${FOUNDER_PROJECTS_URL}${values.currentProjectId}/`, {
                    current_step: currentStep,
                })
            } catch {
                // Non-critical — the step is already set in the reducer for the session
            }
        },

        loadExistingGtm: async () => {
            try {
                const response = await api.founderGtm.get()
                const gtm = response as GTMState
                if (gtm && gtm.status) {
                    actions.setGtmState(gtm)
                    if (gtm.status === 'pending' || gtm.status === 'running') {
                        actions.pollGtmStatus()
                    }
                }
            } catch {
                // No existing state
            }
        },

        generateStrategy: async () => {
            try {
                const response = await api.founderGtm.generate(values.productDescription)
                actions.setGtmState(response as GTMState)
                actions.pollGtmStatus()
            } catch (e: any) {
                actions.setGtmState({ status: 'failed', result: null, error: e.message || 'Request failed' })
                actions.stopGtmPolling()
            }
        },

        pollGtmStatus: async (_, breakpoint) => {
            await breakpoint(POLL_INTERVAL_MS)

            if (!values.gtmPolling) {
                return
            }

            try {
                const response = await api.founderGtm.get()
                const gtm = response as GTMState
                if (gtm && gtm.status) {
                    actions.setGtmState(gtm)
                    if (gtm.status === 'completed' || gtm.status === 'failed') {
                        actions.stopGtmPolling()
                    } else {
                        actions.pollGtmStatus()
                    }
                } else {
                    actions.stopGtmPolling()
                }
            } catch {
                actions.stopGtmPolling()
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadExistingProject()

        const { searchParams } = router.values
        const step = searchParams.step ? parseInt(searchParams.step, 10) : 0
        if (step) {
            actions.setStep(step)
        }

        actions.loadExistingGtm()
    }),

    actionToUrl(({ values }) => ({
        setStep: () => {
            return [router.values.location.pathname, { step: String(values.step) }]
        },
    })),

    urlToAction(({ actions, values }) => ({
        '/init/founder': (_: unknown, searchParams: Record<string, string>) => {
            const step = searchParams.step ? parseInt(searchParams.step, 10) : 0
            if (step !== values.step) {
                actions.setStep(step)
            }
        },
    })),
])
