import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import api from 'lib/api'

import type { founderLogicType } from './founderLogicType'

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

const POLL_INTERVAL_MS = 2000

export const founderLogic = kea<founderLogicType>([
    path(['products', 'founder_mode', 'frontend', 'scenes', 'founderLogic']),

    actions({
        setStep: (step: number) => ({ step }),
        setCurrentProjectId: (projectId: string | null) => ({ projectId }),
        setProductDescription: (description: string) => ({ description }),
        generateStrategy: true,
        setGtmState: (state: GTMState) => ({ state }),
        loadExistingGtm: true,
        pollGtmStatus: true,
        stopGtmPolling: true,
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

    listeners(({ actions, values }) => ({
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
