import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { founderLogic } from '../scenes/founderLogic'
import type { leanCanvasLogicType } from './leanCanvasLogicType'

// Order matches the Lean Canvas fill sequence shown in the canvas image: 1. Problem,
// 2. Customer Segments, 3. USP, 4. Solution, 5. Unfair Advantage, 6. Revenue Stream,
// 7. Cost Structure, 8. Key Metrics, 9. Channels.
export const LEAN_CANVAS_CELL_KEYS = [
    'problem',
    'customer_segments',
    'usp',
    'solution',
    'unfair_advantage',
    'revenue_stream',
    'cost_structure',
    'key_metrics',
    'channels',
] as const

export type LeanCanvasCellKey = (typeof LEAN_CANVAS_CELL_KEYS)[number]

export type LeanCanvasIdeation = Record<LeanCanvasCellKey, string>

export interface LeanCanvasCellConfig {
    key: LeanCanvasCellKey
    order: number // 1-9 — matches the badge numbers in the canvas viz
    title: string
    prompt: string
    helper: string
    placeholder: string
}

// Single source of truth for cell labels / prompts. Keeps the viz and the active-cell panel
// reading from the same data so future copy edits only touch one spot.
export const LEAN_CANVAS_CELLS: LeanCanvasCellConfig[] = [
    {
        key: 'problem',
        order: 1,
        title: 'Problem',
        prompt: 'What pain do your future customers feel today?',
        helper: 'List the top 1-3 problems. Specific symptoms from the customer\'s point of view, not abstract market gaps. Bad: "lack of unified data". Good: "spends 4 hours every Friday reconciling invoices by hand".',
        placeholder: 'e.g. HOA boards burn 4 hours each meeting taking minutes and chasing votes…',
    },
    {
        key: 'customer_segments',
        order: 2,
        title: 'Customer segments',
        prompt: 'Who are your target customers?',
        helper: 'Concrete personas, not categories. Identify your early adopters — the narrowest subset most likely to try first.',
        placeholder: 'e.g. Volunteer HOA board members at 5-200 unit complexes (early adopters: complexes using…)',
    },
    {
        key: 'usp',
        order: 3,
        title: 'Unique value proposition',
        prompt: "What's your single clear, compelling promise?",
        helper: 'One sentence. Try: "For [customer] who [trigger], [your product] is the [category] that [benefit]". No buzzwords.',
        placeholder: 'e.g. The AI cofounder for volunteer HOA boards — agendas, minutes, votes in one place.',
    },
    {
        key: 'solution',
        order: 4,
        title: 'Solution',
        prompt: 'What is the smallest set of features that addresses the problem?',
        helper: 'Top 1-3 features, mapping 1:1 to your problems. Not a roadmap — the sharpest cut you can name.',
        placeholder: 'e.g. Ingest meeting recordings + bylaws, draft agendas, track votes…',
    },
    {
        key: 'unfair_advantage',
        order: 5,
        title: 'Unfair advantage',
        prompt: "What's hard for competitors to copy or buy?",
        helper: 'Domain knowledge, network, exclusive data, regulatory edge, prior community. "First-mover" and "great team" don\'t count. If you don\'t have one yet, say so honestly.',
        placeholder: 'e.g. I sit on three HOA boards and run a 400-member homeowner forum…',
    },
    {
        key: 'revenue_stream',
        order: 6,
        title: 'Revenue stream',
        prompt: 'How will the business make money?',
        helper: 'Model (subscription / usage / one-time / marketplace), price point or range, and gross margin assumption. One short paragraph.',
        placeholder: 'e.g. $5/unit/month SaaS, billed annually, ~80% gross margin after LLM costs.',
    },
    {
        key: 'cost_structure',
        order: 7,
        title: 'Cost structure',
        prompt: 'What are the biggest operating costs?',
        helper: 'Top 1-5 expected costs in order of size. Include fixed (infra, salaries) and variable (LLM, CAC, support).',
        placeholder: 'e.g. LLM inference, founder salary, customer acquisition, infra…',
    },
    {
        key: 'key_metrics',
        order: 8,
        title: 'Key metrics',
        prompt: 'Which 1-4 metrics tell you the business is working?',
        helper: 'Leading indicators of customer value (activation, retention) beat vanity metrics (signups, traffic). One metric per item.',
        placeholder: 'e.g. Active boards / month, meetings managed, retention at 30 days…',
    },
    {
        key: 'channels',
        order: 9,
        title: 'Channels',
        prompt: 'How will you reach your customers?',
        helper: 'Specific channel AND motion. "Founder-led outbound on LinkedIn" beats "social media". Mix free and paid if relevant.',
        placeholder: 'e.g. Founder-led outbound to HOA management companies, NextDoor groups, HOA conferences…',
    },
]

const FOUNDER_PROJECTS_URL = 'api/projects/@current/founder_projects/'
const projectDetailUrl = (projectId: string): string => `${FOUNDER_PROJECTS_URL}${projectId}/`

// Cap auto-derived project names so we stay safely under the 200-char db limit.
const NAME_FROM_TEXT_LIMIT = 80

function deriveProjectName(ideation: LeanCanvasIdeation): string {
    const seed = ideation.problem || ideation.usp || ideation.solution
    const trimmed = seed.trim()
    if (!trimmed) {
        return 'Untitled idea'
    }
    return trimmed.length > NAME_FROM_TEXT_LIMIT ? `${trimmed.slice(0, NAME_FROM_TEXT_LIMIT).trim()}…` : trimmed
}

const EMPTY_IDEATION: LeanCanvasIdeation = LEAN_CANVAS_CELL_KEYS.reduce((acc, key) => {
    acc[key] = ''
    return acc
}, {} as LeanCanvasIdeation)

// Demo content used by the prefill debug button — modeled on the "HOA cofounder" sample
// idea from earlier hackathon sessions. Keep it concrete and opinionated so the rendered
// canvas looks like real founder thinking rather than placeholder lorem.
const SAMPLE_IDEATION: LeanCanvasIdeation = {
    problem:
        'HOA boards burn 4 hours each meeting taking minutes, chasing votes, and reconciling bylaws. Existing software is clunky and built for property managers, not volunteer boards.',
    customer_segments:
        'Volunteer HOA board members at 5-200 unit complexes. Early adopters: complexes already using Google Workspace and frustrated by current minute-taking tools.',
    usp: 'The AI cofounder for volunteer HOA boards — agendas, minutes, votes in one place, drafted from your bylaws and meeting recordings.',
    solution:
        'Ingest meeting recordings + bylaws. Draft agendas. Summarize decisions. Track votes with full audit trail.',
    unfair_advantage:
        'Founder sits on three HOA boards and runs a 400-member homeowner forum. Hands-on community context most competitors lack.',
    revenue_stream: '$5/unit/month SaaS, billed annually. Estimated ~80% gross margin after LLM inference costs.',
    cost_structure: 'LLM inference, founder salary, customer acquisition, infrastructure, customer support.',
    key_metrics:
        'Active boards per month, meetings managed, 30-day retention, time saved per meeting (target: 2+ hours).',
    channels:
        'Founder-led outbound to HOA management companies, NextDoor groups, HOA-focused subreddits, HOA conferences.',
}

// Step 2's validation pipeline (logic/validation/schemas.py::IdeationInput) reads
// {what, how, who, problem} from the saved ideation. We project the richer canvas onto
// those four legacy keys so the existing pipeline keeps working without backend changes.
// Mapping:
//   what    → unique value proposition (the customer-facing promise)
//   how     → solution (the features that deliver on the promise)
//   who     → customer segments (target + early adopters)
//   problem → problem (already aligned)
function deriveLegacyIdeationFields(canvas: LeanCanvasIdeation): {
    what: string
    how: string
    who: string
    problem: string
} {
    return {
        what: canvas.usp,
        how: canvas.solution,
        who: canvas.customer_segments,
        problem: canvas.problem,
    }
}

interface FounderProjectResponse {
    id: string
    name: string
    ideation: Record<string, unknown>
}

export const leanCanvasLogic = kea<leanCanvasLogicType>([
    path(['products', 'founder_mode', 'frontend', 'components', 'leanCanvasLogic']),

    connect(() => ({
        values: [founderLogic, ['currentProjectId']],
        actions: [founderLogic, ['setCurrentProjectId', 'setStep']],
    })),

    actions({
        setCellValue: (key: LeanCanvasCellKey, value: string) => ({ key, value }),
        goToCell: (index: number) => ({ index }),
        nextCell: true,
        previousCell: true,
        saveProgress: true,
        completeAndContinue: true,
        prefillSample: true,
    }),

    reducers({
        ideation: [
            EMPTY_IDEATION,
            {
                setCellValue: (state, { key, value }) => ({ ...state, [key]: value }),
                prefillSample: () => SAMPLE_IDEATION,
            },
        ],
        currentCellIndex: [
            0,
            {
                goToCell: (_, { index }) => clampIndex(index),
                nextCell: (state) => clampIndex(state + 1),
                previousCell: (state) => clampIndex(state - 1),
            },
        ],
        // Set when the founder hits "Save & continue" on the last cell. Cleared once the
        // save lands and we've advanced founderLogic to step 2. Without this, completeAndContinue
        // would advance synchronously and the validation step would briefly load against a
        // project that doesn't exist yet.
        pendingAdvance: [
            false,
            {
                completeAndContinue: () => true,
                setStep: () => false,
            },
        ],
    }),

    loaders(({ values }) => ({
        savedProject: [
            null as FounderProjectResponse | null,
            {
                // Single endpoint covers both create (no project yet) and update (incremental
                // save after a Next click). The current_project_id is connected from founderLogic
                // so subsequent saves PATCH instead of creating duplicates.
                saveProgress: async () => {
                    // Spread the canvas state with the legacy {what, how, who, problem} shape
                    // so Step 2's IdeationInput pydantic schema accepts the payload. The two
                    // shapes coexist in the same JSON column — the canvas keys carry richer
                    // context for future consumers, the legacy keys keep validation working.
                    const ideation = {
                        ...values.ideation,
                        ...deriveLegacyIdeationFields(values.ideation),
                    }
                    if (values.currentProjectId) {
                        return await api.update<FounderProjectResponse>(projectDetailUrl(values.currentProjectId), {
                            ideation,
                        })
                    }
                    return await api.create<FounderProjectResponse>(FOUNDER_PROJECTS_URL, {
                        name: deriveProjectName(values.ideation),
                        ideation,
                    })
                },
            },
        ],
    })),

    selectors({
        currentCell: [
            (s) => [s.currentCellIndex],
            (index): LeanCanvasCellConfig => LEAN_CANVAS_CELLS[clampIndex(index)],
        ],
        // Map of cell key -> filled boolean, derived once so the viz cells can subscribe
        // individually without each running its own truthy check.
        filledByKey: [
            (s) => [s.ideation],
            (ideation): Record<LeanCanvasCellKey, boolean> => {
                const result: Record<string, boolean> = {}
                for (const key of LEAN_CANVAS_CELL_KEYS) {
                    result[key] = ideation[key].trim().length > 0
                }
                return result as Record<LeanCanvasCellKey, boolean>
            },
        ],
        filledCount: [(s) => [s.filledByKey], (filled): number => Object.values(filled).filter(Boolean).length],
        isLastCell: [(s) => [s.currentCellIndex], (index): boolean => index === LEAN_CANVAS_CELL_KEYS.length - 1],
        isFirstCell: [(s) => [s.currentCellIndex], (index): boolean => index === 0],
    }),

    listeners(({ actions, values }) => ({
        // Save when leaving each cell (next or previous), so progress is durable. The first
        // call POSTs and the auto-captured project id then routes all subsequent saves to
        // PATCH. We avoid a saving loop by skipping the save when the ideation is entirely
        // empty.
        nextCell: () => {
            if (hasAnyAnswer(values.ideation)) {
                actions.saveProgress()
            }
        },
        previousCell: () => {
            if (hasAnyAnswer(values.ideation)) {
                actions.saveProgress()
            }
        },
        goToCell: () => {
            if (hasAnyAnswer(values.ideation)) {
                actions.saveProgress()
            }
        },
        saveProgressSuccess: ({ savedProject }) => {
            // Persist the id on founderLogic so any other step (validation, gtm) finds it.
            if (savedProject?.id && !values.currentProjectId) {
                actions.setCurrentProjectId(savedProject.id)
            }
            // If the user clicked "Save & continue" on the last cell, wait for the POST to
            // land before advancing — that way validation step loads with a project that
            // actually exists.
            if (values.pendingAdvance) {
                actions.setStep(2)
            }
        },
        completeAndContinue: () => {
            actions.saveProgress()
        },
        // Debug-only convenience: drop a complete sample canvas into state, jump to the last
        // cell (so the next click is "Save & continue"), and persist immediately. Useful for
        // skipping through the flow during dev / demos.
        prefillSample: () => {
            actions.goToCell(LEAN_CANVAS_CELL_KEYS.length - 1)
            actions.saveProgress()
        },
    })),
])

function clampIndex(index: number): number {
    if (index < 0) {
        return 0
    }
    if (index >= LEAN_CANVAS_CELL_KEYS.length) {
        return LEAN_CANVAS_CELL_KEYS.length - 1
    }
    return index
}

function hasAnyAnswer(ideation: LeanCanvasIdeation): boolean {
    return LEAN_CANVAS_CELL_KEYS.some((key) => ideation[key].trim().length > 0)
}
