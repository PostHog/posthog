import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import type { founderLogicType } from './founderLogicType'

export type FounderStep = 'ideation' | 'validation' | 'gtm' | 'mvp' | 'marketing'

export const FOUNDER_STEPS: FounderStep[] = ['ideation', 'validation', 'gtm', 'mvp', 'marketing']

import type {
    GTMEnvelopeApi,
    GTMSummaryApi,
    MarketingStepsEnvelopeApi,
    MVPEnvelopeApi,
    MVPHappyPathApi,
    PracticalStepsResultApi,
} from '../generated/api.schemas'

interface FounderProjectListItem {
    id: string
    name: string
    current_step: FounderStep
}

const POLL_INTERVAL_MS = 2000
const FOUNDER_PROJECTS_URL = 'api/projects/@current/founder_projects/'

interface JSONContent {
    type: string
    content?: JSONContent[]
    text?: string
    attrs?: Record<string, unknown>
    marks?: Array<{ type: string; attrs?: Record<string, unknown> }>
}

function text(t: string): JSONContent {
    return { type: 'text', text: t }
}

function paragraph(...children: JSONContent[]): JSONContent {
    return { type: 'paragraph', content: children }
}

function heading(level: number, t: string): JSONContent {
    return { type: 'heading', attrs: { level }, content: [text(t)] }
}

function bulletList(items: string[]): JSONContent {
    return {
        type: 'bulletList',
        content: items.map((item) => ({
            type: 'listItem',
            content: [paragraph(text(item))],
        })),
    }
}

function buildNotebookContent(project: Record<string, unknown>): JSONContent {
    const nodes: JSONContent[] = []

    // Ideation
    nodes.push(heading(1, 'Ideation'))
    const ideation = project.ideation as Record<string, string> | null
    if (ideation) {
        if (ideation.idea || ideation.problem) {
            nodes.push(paragraph(text(ideation.idea || ideation.problem)))
        }
        const ideationDetails: string[] = []
        if (ideation.what) {
            ideationDetails.push(`What: ${ideation.what}`)
        }
        if (ideation.how) {
            ideationDetails.push(`How: ${ideation.how}`)
        }
        if (ideation.who) {
            ideationDetails.push(`Who: ${ideation.who}`)
        }
        if (ideationDetails.length > 0) {
            nodes.push(bulletList(ideationDetails))
        }
    } else {
        nodes.push(paragraph(text('Not completed yet.')))
    }

    // Validation
    nodes.push(heading(1, 'Validation'))
    const validation = project.validation as Record<string, unknown> | null
    const valReport = validation?.report as Record<string, unknown> | null
    if (valReport) {
        const verdict = valReport.verdict as Record<string, unknown> | null
        if (verdict) {
            nodes.push(
                paragraph(text(`Score: ${verdict.score}/10 — Confidence: ${verdict.confidence} — ${verdict.rationale}`))
            )
        }
        const competitors = valReport.competitors as Array<Record<string, string>> | null
        if (competitors?.length) {
            nodes.push(heading(2, 'Competitors'))
            nodes.push(bulletList(competitors.map((c) => `${c.name}: ${c.positioning || c.description}`)))
        }
        const diff = valReport.differentiation as Record<string, string> | null
        if (diff) {
            nodes.push(heading(2, 'Differentiation'))
            nodes.push(paragraph(text(diff.summary)))
            if (diff.moat) {
                nodes.push(paragraph(text(`Moat: ${diff.moat}`)))
            }
        }
    } else {
        nodes.push(paragraph(text('Not completed yet.')))
    }

    // GTM
    nodes.push(heading(1, 'Go-to-market'))
    const gtm = project.gtm as Record<string, unknown> | null
    const gtmResult = gtm?.result as Record<string, unknown> | null
    if (gtmResult) {
        if (gtmResult.positioning_statement) {
            nodes.push(paragraph(text(gtmResult.positioning_statement as string)))
        }
        const segment = gtmResult.primary_segment as Record<string, string> | null
        if (segment) {
            nodes.push(heading(2, 'Primary segment'))
            nodes.push(paragraph(text(`${segment.name}: ${segment.description}`)))
        }
        if (gtmResult.moat) {
            nodes.push(paragraph(text(`Moat: ${gtmResult.moat as string}`)))
        }
        if (gtmResult.pricing_philosophy) {
            nodes.push(heading(2, 'Pricing'))
            nodes.push(paragraph(text(gtmResult.pricing_philosophy as string)))
        }
        const channels = [
            gtmResult.primary_channel as string,
            ...((gtmResult.secondary_channels as string[]) || []),
        ].filter(Boolean)
        if (channels.length) {
            nodes.push(heading(2, 'Channels'))
            nodes.push(bulletList(channels))
        }
    } else {
        nodes.push(paragraph(text('Not completed yet.')))
    }

    // MVP
    nodes.push(heading(1, 'MVP spec'))
    const mvp = project.mvp as Record<string, unknown> | null
    const mvpResult = mvp?.result as Record<string, unknown> | null
    if (mvpResult) {
        if (mvpResult.one_liner) {
            nodes.push(paragraph(text(mvpResult.one_liner as string)))
        }
        const flow = mvpResult.core_flow as Array<Record<string, string | number>> | null
        if (flow?.length) {
            nodes.push(heading(2, 'Core flow'))
            nodes.push(
                bulletList(
                    flow.map((s) => `${s.step}. ${s.user_action} → ${s.system_response} (✓ ${s.success_signal})`)
                )
            )
        }
        const mustHaves = mvpResult.must_haves as string[] | null
        if (mustHaves?.length) {
            nodes.push(heading(2, 'Must-haves'))
            nodes.push(bulletList(mustHaves))
        }
        const excluded = mvpResult.deliberately_excluded as string[] | null
        if (excluded?.length) {
            nodes.push(heading(2, 'Deliberately excluded'))
            nodes.push(bulletList(excluded))
        }
    } else {
        nodes.push(paragraph(text('Not completed yet.')))
    }

    // Marketing
    nodes.push(heading(1, 'Marketing plan'))
    const marketing = project.marketing_steps as Record<string, unknown> | null
    const mktResult = marketing?.result as Record<string, unknown> | null
    if (mktResult) {
        if (mktResult.launch_summary) {
            nodes.push(paragraph(text(mktResult.launch_summary as string)))
        }
        const communities = mktResult.target_communities as string[] | null
        if (communities?.length) {
            nodes.push(heading(2, 'Target communities'))
            nodes.push(bulletList(communities))
        }
        const steps = mktResult.steps as Array<Record<string, unknown>> | null
        if (steps?.length) {
            nodes.push(heading(2, 'Launch steps'))
            for (const step of steps) {
                nodes.push(
                    heading(3, `${step.title as string} (${step.channel as string} · ${step.timeline as string})`)
                )
                nodes.push(paragraph(text(step.description as string)))
                const posts = step.ready_to_use_content as Array<Record<string, string>> | null
                if (posts?.length) {
                    for (const post of posts) {
                        nodes.push(heading(4, platformLabel(post.platform)))
                        nodes.push(paragraph(text(post.content)))
                        if (post.tips) {
                            nodes.push(paragraph(text(`💡 ${post.tips}`)))
                        }
                    }
                }
            }
        }
    } else {
        nodes.push(paragraph(text('Not completed yet.')))
    }

    return { type: 'doc', content: nodes }
}

function platformLabel(raw: string): string {
    const labels: Record<string, string> = {
        product_hunt: 'Product Hunt',
        producthunt: 'Product Hunt',
        linkedin: 'LinkedIn',
        twitter: 'Twitter / X',
        'twitter/x': 'Twitter / X',
        reddit: 'Reddit',
        hacker_news: 'Hacker News',
        hackernews: 'Hacker News',
        indie_hackers: 'Indie Hackers',
    }
    return labels[raw.toLowerCase()] ?? raw
}

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
        triggerMvp: true,
        setMvpEnvelope: (mvp: MVPEnvelopeApi | null) => ({ mvp }),
        setMvpLoaded: (loaded: boolean) => ({ loaded }),
        loadExistingProject: true,
        loadExistingGtm: true,
        loadExistingMvp: true,
        pollGtmStatus: true,
        stopGtmPolling: true,
        pollMvpStatus: true,
        stopMvpPolling: true,
        triggerMarketing: true,
        setMarketingEnvelope: (marketing: MarketingStepsEnvelopeApi | null) => ({ marketing }),
        setMarketingLoaded: (loaded: boolean) => ({ loaded }),
        loadExistingMarketing: true,
        pollMarketingStatus: true,
        stopMarketingPolling: true,
        setProjectLoaded: (loaded: boolean) => ({ loaded }),
        exportToNotebook: true,
        setExporting: (exporting: boolean) => ({ exporting }),
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
        mvpEnvelope: [
            null as MVPEnvelopeApi | null,
            {
                setMvpEnvelope: (_, { mvp }) => mvp,
                triggerMvp: () => ({ status: 'running' }) as MVPEnvelopeApi,
            },
        ],
        mvpLoaded: [
            false,
            {
                setMvpLoaded: (_, { loaded }) => loaded,
            },
        ],
        mvpPolling: [
            false,
            {
                triggerMvp: () => true,
                stopMvpPolling: () => false,
            },
        ],
        marketingEnvelope: [
            null as MarketingStepsEnvelopeApi | null,
            {
                setMarketingEnvelope: (_, { marketing }) => marketing,
                triggerMarketing: () => ({ status: 'running' }) as MarketingStepsEnvelopeApi,
            },
        ],
        marketingLoaded: [
            false,
            {
                setMarketingLoaded: (_, { loaded }) => loaded,
            },
        ],
        marketingPolling: [
            false,
            {
                triggerMarketing: () => true,
                stopMarketingPolling: () => false,
            },
        ],
        exporting: [
            false,
            {
                setExporting: (_, { exporting }) => exporting,
            },
        ],
    }),

    selectors({
        hasExistingProject: [(s) => [s.currentProjectId], (id): boolean => id !== null],
        gtmStatus: [(s) => [s.gtmEnvelope], (gtm): string => gtm?.status ?? 'idle'],
        gtmResult: [(s) => [s.gtmEnvelope], (gtm): GTMSummaryApi | null => gtm?.result ?? null],
        gtmIsRunning: [(s) => [s.gtmStatus], (status): boolean => status === 'pending' || status === 'running'],
        gtmError: [(s) => [s.gtmEnvelope], (gtm): string => gtm?.error ?? ''],
        mvpStatus: [(s) => [s.mvpEnvelope], (mvp): string => mvp?.status ?? 'idle'],
        mvpResult: [(s) => [s.mvpEnvelope], (mvp): MVPHappyPathApi | null => mvp?.result ?? null],
        mvpIsRunning: [(s) => [s.mvpStatus], (status): boolean => status === 'pending' || status === 'running'],
        mvpError: [(s) => [s.mvpEnvelope], (mvp): string => mvp?.error ?? ''],
        marketingStatus: [(s) => [s.marketingEnvelope], (m): string => m?.status ?? 'idle'],
        marketingResult: [(s) => [s.marketingEnvelope], (m): PracticalStepsResultApi | null => m?.result ?? null],
        marketingIsRunning: [
            (s) => [s.marketingStatus],
            (status): boolean => status === 'pending' || status === 'running',
        ],
        marketingError: [(s) => [s.marketingEnvelope], (m): string => m?.error ?? ''],
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
            actions.loadExistingMvp()
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

        loadExistingMvp: async () => {
            if (!values.currentProjectId) {
                actions.setMvpLoaded(true)
                return
            }
            try {
                const project = await api.get<{ mvp: MVPEnvelopeApi | null }>(
                    `${FOUNDER_PROJECTS_URL}${values.currentProjectId}/`
                )
                if (project.mvp?.status) {
                    actions.setMvpEnvelope(project.mvp)
                    if (project.mvp.status === 'pending' || project.mvp.status === 'running') {
                        actions.pollMvpStatus()
                    }
                }
            } catch {
                // No existing state
            }
            actions.setMvpLoaded(true)
            actions.loadExistingMarketing()
        },

        triggerMvp: async () => {
            if (!values.currentProjectId) {
                return
            }
            try {
                const project = await api.create<{ mvp: MVPEnvelopeApi }>(
                    `${FOUNDER_PROJECTS_URL}${values.currentProjectId}/run_mvp/`
                )
                actions.setMvpEnvelope(project.mvp)
                actions.pollMvpStatus()
            } catch (e: unknown) {
                const msg = e instanceof Error ? e.message : 'Request failed'
                actions.setMvpEnvelope({ status: 'failed', error: msg })
                actions.stopMvpPolling()
            }
        },

        pollMvpStatus: async (_, breakpoint) => {
            await breakpoint(POLL_INTERVAL_MS)
            if (!values.mvpPolling || !values.currentProjectId) {
                return
            }
            try {
                const project = await api.get<{ mvp: MVPEnvelopeApi | null }>(
                    `${FOUNDER_PROJECTS_URL}${values.currentProjectId}/`
                )
                if (project.mvp?.status) {
                    actions.setMvpEnvelope(project.mvp)
                    if (project.mvp.status === 'completed' || project.mvp.status === 'failed') {
                        actions.stopMvpPolling()
                    } else {
                        actions.pollMvpStatus()
                    }
                } else {
                    actions.stopMvpPolling()
                }
            } catch {
                actions.stopMvpPolling()
            }
        },

        loadExistingMarketing: async () => {
            if (!values.currentProjectId) {
                actions.setMarketingLoaded(true)
                return
            }
            try {
                const project = await api.get<{ marketing_steps: MarketingStepsEnvelopeApi | null }>(
                    `${FOUNDER_PROJECTS_URL}${values.currentProjectId}/`
                )
                if (project.marketing_steps?.status) {
                    actions.setMarketingEnvelope(project.marketing_steps)
                    if (project.marketing_steps.status === 'pending' || project.marketing_steps.status === 'running') {
                        actions.pollMarketingStatus()
                    }
                }
            } catch {
                // No existing state
            }
            actions.setMarketingLoaded(true)
        },

        triggerMarketing: async () => {
            if (!values.currentProjectId) {
                return
            }
            try {
                const project = await api.create<{ marketing_steps: MarketingStepsEnvelopeApi }>(
                    `${FOUNDER_PROJECTS_URL}${values.currentProjectId}/run_practical_steps/`
                )
                actions.setMarketingEnvelope(project.marketing_steps)
                actions.pollMarketingStatus()
            } catch (e: unknown) {
                const msg = e instanceof Error ? e.message : 'Request failed'
                actions.setMarketingEnvelope({ status: 'failed', error: msg })
                actions.stopMarketingPolling()
            }
        },

        pollMarketingStatus: async (_, breakpoint) => {
            await breakpoint(POLL_INTERVAL_MS)
            if (!values.marketingPolling || !values.currentProjectId) {
                return
            }
            try {
                const project = await api.get<{ marketing_steps: MarketingStepsEnvelopeApi | null }>(
                    `${FOUNDER_PROJECTS_URL}${values.currentProjectId}/`
                )
                if (project.marketing_steps?.status) {
                    actions.setMarketingEnvelope(project.marketing_steps)
                    if (project.marketing_steps.status === 'completed' || project.marketing_steps.status === 'failed') {
                        actions.stopMarketingPolling()
                    } else {
                        actions.pollMarketingStatus()
                    }
                } else {
                    actions.stopMarketingPolling()
                }
            } catch {
                actions.stopMarketingPolling()
            }
        },

        exportToNotebook: async () => {
            if (!values.currentProjectId) {
                return
            }
            actions.setExporting(true)
            try {
                const project = await api.get<Record<string, unknown>>(
                    `${FOUNDER_PROJECTS_URL}${values.currentProjectId}/`
                )
                const content = buildNotebookContent(project)
                const notebook = await api.notebooks.create({
                    title: `Founder mode — ${(project.name as string) || 'Untitled'}`,
                    content,
                    text_content: null,
                })
                lemonToast.success('Notebook created!')
                router.actions.push(`/notebooks/${notebook.short_id}`)
            } catch {
                lemonToast.error('Failed to create notebook')
            }
            actions.setExporting(false)
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
