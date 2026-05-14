import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import api from 'lib/api'

import type { founderLogicType } from './founderLogicType'

export type FounderStep = 'ideation' | 'validation' | 'gtm' | 'mvp' | 'marketing'

export const FOUNDER_STEPS: FounderStep[] = ['ideation', 'validation', 'gtm', 'mvp', 'marketing']

import type { GTMEnvelopeApi, GTMSummaryApi } from '../generated/api.schemas'

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
        triggerGtm: true,
        setGtmEnvelope: (gtm: GTMEnvelopeApi | null) => ({ gtm }),
        setGtmLoaded: (loaded: boolean) => ({ loaded }),
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
        gtmEnvelope: [
            null as GTMEnvelopeApi | null,
            {
                setGtmEnvelope: (_, { gtm }) => gtm,
                triggerGtm: () => ({ status: 'running' }) as GTMEnvelopeApi,
            },
        ],
        gtmLoaded: [
            false,
            {
                setGtmLoaded: (_, { loaded }) => loaded,
            },
        ],
        gtmPolling: [
            false,
            {
                triggerGtm: () => true,
                stopGtmPolling: () => false,
            },
        ],
    }),

    selectors({
        hasExistingProject: [(s) => [s.currentProjectId], (id): boolean => id !== null],
        gtmStatus: [(s) => [s.gtmEnvelope], (gtm): string => gtm?.status ?? 'idle'],
        gtmResult: [(s) => [s.gtmEnvelope], (gtm): GTMSummaryApi | null => gtm?.result ?? null],
        gtmIsRunning: [(s) => [s.gtmStatus], (status): boolean => status === 'pending' || status === 'running'],
        gtmError: [(s) => [s.gtmEnvelope], (gtm): string => gtm?.error ?? ''],
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
            actions.loadExistingGtm()
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
            if (!values.currentProjectId) {
                actions.setGtmLoaded(true)
                return
            }
            try {
                const project = await api.get<{ gtm: GTMEnvelopeApi | null }>(
                    `${FOUNDER_PROJECTS_URL}${values.currentProjectId}/`
                )
                if (project.gtm?.status) {
                    actions.setGtmEnvelope(project.gtm)
                    if (project.gtm.status === 'pending' || project.gtm.status === 'running') {
                        actions.pollGtmStatus()
                    }
                }
            } catch {
                // No existing state
            }
            actions.setGtmLoaded(true)
        },

        triggerGtm: async () => {
            if (!values.currentProjectId) {
                return
            }
            try {
                const project = await api.create<{ gtm: GTMEnvelopeApi }>(
                    `${FOUNDER_PROJECTS_URL}${values.currentProjectId}/run_gtm/`
                )
                actions.setGtmEnvelope(project.gtm)
                actions.pollGtmStatus()
            } catch (e: unknown) {
                const msg = e instanceof Error ? e.message : 'Request failed'
                actions.setGtmEnvelope({ status: 'failed', error: msg })
                actions.stopGtmPolling()
            }
        },

        pollGtmStatus: async (_, breakpoint) => {
            await breakpoint(POLL_INTERVAL_MS)
            if (!values.gtmPolling || !values.currentProjectId) {
                return
            }
            try {
                const project = await api.get<{ gtm: GTMEnvelopeApi | null }>(
                    `${FOUNDER_PROJECTS_URL}${values.currentProjectId}/`
                )
                if (project.gtm?.status) {
                    actions.setGtmEnvelope(project.gtm)
                    if (project.gtm.status === 'completed' || project.gtm.status === 'failed') {
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
