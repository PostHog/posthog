import { describe, expect, it, vi } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/signals'
import type { Context } from '@/tools/types'

const scoutId = '00000000-0000-4000-8000-000000000001'
const comparisonId = '00000000-0000-4000-8000-000000000002'
const baselineId = '00000000-0000-4000-8000-000000000003'
const candidateId = '00000000-0000-4000-8000-000000000004'
const generationId = '00000000-0000-4000-8000-000000000005'
const launchId = '00000000-0000-4000-8000-000000000006'
const contextId = '00000000-0000-4000-8000-000000000007'
const configPath = `/api/projects/2/signals/scout/configs/${scoutId}`
const rubricPath = `/api/projects/2/signals/scout/rubrics/${scoutId}`

function createContext(response: unknown): { context: Context; request: ReturnType<typeof vi.fn> } {
    const request = vi.fn().mockResolvedValue(response)
    const context = {
        api: { request },
        stateManager: { getProjectId: async () => '2' },
    } as unknown as Context
    return { context, request }
}

describe('Generated scout trial workflow tools', () => {
    it('returns the source prompt and per-model efforts from the requested saved context', async () => {
        const setup = {
            config_id: scoutId,
            skill_version: 3,
            skill_body: 'Inspect the synthetic inventory before updating the report.\n',
            ready: true,
            blocked_reason: null,
            models: [
                { model: 'gpt-6-luna', reasoning_efforts: ['low', 'medium'] },
                { model: 'gpt-6-sol', reasoning_efforts: ['medium', 'high'] },
            ],
        }
        const { context, request } = createContext(setup)
        const tool = GENERATED_TOOLS['scout-trial-setup']!()

        expect(await tool.handler(context, tool.schema.parse({ id: scoutId, context_id: contextId }))).toEqual(setup)
        expect(request).toHaveBeenCalledWith({
            method: 'GET',
            path: `${configPath}/trial_setup/`,
            query: { context_id: contextId },
        })
    })

    it('starts the automatic comparison with unchanged prompts, model choices, repeats and retry IDs', async () => {
        const body = {
            comparison_id: comparisonId,
            baseline_variant_id: baselineId,
            expected_skill_version: 3,
            note: 'Compare the inventory review approaches.',
            variants: [
                {
                    id: baselineId,
                    label: 'Original instructions',
                    launch_ids: [launchId, '00000000-0000-4000-8000-000000000008'],
                    model: 'gpt-6-luna',
                    reasoning_effort: 'low',
                },
                {
                    id: candidateId,
                    label: 'Verify first',
                    launch_ids: ['00000000-0000-4000-8000-000000000009'],
                    model: 'gpt-6-sol',
                    reasoning_effort: 'high',
                    skill_body: '\nInspect the synthetic inventory.\n  Verify counts before editing.\n',
                },
            ],
        }
        const response = { comparison_id: comparisonId, status: 'starting', evaluation: null }
        const { context, request } = createContext(response)
        const tool = GENERATED_TOOLS['scout-trial-start']!()

        for (let attempt = 0; attempt < 2; attempt++) {
            expect(await tool.handler(context, tool.schema.parse({ id: scoutId, ...body }))).toEqual(response)
        }

        expect(request.mock.calls.map(([call]) => call)).toEqual([
            { method: 'POST', path: `${configPath}/trial_comparison/`, body },
            { method: 'POST', path: `${configPath}/trial_comparison/`, body },
        ])
    })

    it('adopts a reviewed rubric and forwards later full-set edits without replacing its reference', async () => {
        const criteria = ['evidence', 'clarity', 'actionability', 'priority', 'instructions', 'memory'].map((key) => ({
            id: `default-${key}`,
            title: `Check ${key}`,
            description: `Review ${key} in the inventory audit.`,
            pass_condition: 'The recorded evidence supports the finding.',
            applicability: 'When the audit produces a finding.',
            enabled: key !== 'actionability',
            source: 'default',
        }))
        criteria.push({
            id: 'custom-generated-counts',
            title: 'Support inventory counts',
            description: 'Ground inventory totals in the recorded query result.',
            pass_condition: 'The summary cites the verified inventory totals.',
            applicability: 'When the scout reports inventory totals.',
            enabled: true,
            source: 'custom',
        })
        const body = { revision: 4, criteria, adopt_generation_id: generationId }
        const response = { config_id: scoutId, revision: 5, criteria, reference_generation_id: generationId }
        const { context, request } = createContext(response)
        const tool = GENERATED_TOOLS['scout-rubric-save']!()

        expect(await tool.handler(context, tool.schema.parse({ id: scoutId, ...body }))).toEqual(response)
        expect(request).toHaveBeenCalledWith({ method: 'PUT', path: `${rubricPath}/`, body })

        const added = [
            ...criteria.map((criterion) =>
                criterion.id === 'default-evidence' ? { ...criterion, enabled: false } : criterion
            ),
            {
                id: 'custom-inventory-order',
                title: 'Verify before editing',
                description: 'Check inventory counts before changing the report.',
                pass_condition: 'A count verification precedes the edit.',
                applicability: 'When the scout edits a report.',
                enabled: true,
                source: 'custom',
            },
        ]
        const edited = added.map((criterion) => {
            if (criterion.id === 'default-evidence') {
                return { ...criterion, enabled: true }
            }
            if (criterion.id === 'custom-inventory-order') {
                return {
                    ...criterion,
                    description: 'Independently verify counts before changing the report.',
                    pass_condition: 'A successful query result arrives before the first edit is submitted.',
                }
            }
            return criterion
        })
        const defaultsOnly = edited.filter((criterion) => criterion.source === 'default')

        for (const [index, completeSet] of [added, edited, defaultsOnly].entries()) {
            const edit = { revision: 5 + index, criteria: completeSet }
            const saved = { ...response, revision: edit.revision + 1, criteria: completeSet }
            request.mockResolvedValueOnce(saved)

            expect(await tool.handler(context, tool.schema.parse({ id: scoutId, ...edit }))).toEqual(saved)
            expect(request).toHaveBeenNthCalledWith(index + 2, { method: 'PUT', path: `${rubricPath}/`, body: edit })
        }
    })

    it('starts suggestions without adopting them and reads the captured reference alongside the saved one', async () => {
        const response = {
            config_id: scoutId,
            revision: 4,
            reference_generation_id: null,
            reference_context: null,
            generation: {
                id: generationId,
                status: 'completed',
                error: null,
                summary: 'Two source instructions disagree about the optional inventory appendix.',
                reference_context: { instructions: 'Verify inventory counts before editing the report.' },
                suggestions: [],
            },
        }
        const { context, request } = createContext(response)
        const generate = GENERATED_TOOLS['scout-rubric-generate']!()
        const get = GENERATED_TOOLS['scout-rubric-get']!()

        await generate.handler(
            context,
            generate.schema.parse({ id: scoutId, context: 'Check the required order and optional appendix.' })
        )
        expect(request).toHaveBeenNthCalledWith(1, {
            method: 'POST',
            path: `${rubricPath}/generate/`,
            body: { context: 'Check the required order and optional appendix.' },
        })
        expect(await get.handler(context, get.schema.parse({ id: scoutId }))).toEqual(response)
        expect(request).toHaveBeenNthCalledWith(2, { method: 'GET', path: `${rubricPath}/` })

        const poll = get.schema.parse({ id: scoutId, fields: ['revision', 'generation.status', 'generation.error'] })
        expect(await get.handler(context, poll)).toEqual({
            revision: 4,
            generation: { status: 'completed', error: null },
        })
        expect(request).toHaveBeenLastCalledWith({ method: 'GET', path: `${rubricPath}/` })

        const beforeGeneration = { ...response, generation: null }
        request.mockResolvedValue(beforeGeneration)
        expect(await get.handler(context, poll)).toEqual({ revision: 4 })
        expect(await get.handler(context, get.schema.parse({ id: scoutId }))).toEqual(beforeGeneration)
    })

    it('keeps judgment reasons, evidence, unknown results and ranking limitations in the report', async () => {
        const response = {
            comparison_id: comparisonId,
            status: 'completed',
            error: null,
            evaluation: {
                status: 'completed',
                error: null,
                report: {
                    outcome: { status: 'inconclusive', variant_ids: [], summary: 'Too few runs could be judged.' },
                    variants: [{ variant_id: candidateId, score: null, coverage: 0, judge_errors: 1 }],
                    runs: [
                        {
                            launch_id: launchId,
                            variant_id: baselineId,
                            status: 'judged',
                            score: null,
                            criteria: [
                                {
                                    criterion_id: 'custom-inventory-order',
                                    verdict: 'unknown',
                                    reason: 'The tool response does not establish when the verification finished.',
                                    confidence: 'low',
                                    evidence: [{ source_id: 'trace-1', quote: 'Verification is still pending.' }],
                                },
                            ],
                        },
                        { variant_id: candidateId, status: 'judge_error', error: 'Judge did not return a result.' },
                    ],
                    limitations: ['Missing evidence must not be counted as a failed criterion.'],
                },
            },
        }
        const { context, request } = createContext(response)
        const tool = GENERATED_TOOLS['scout-trial-report']!()

        expect(await tool.handler(context, tool.schema.parse({ id: scoutId, comparison_id: comparisonId }))).toEqual(
            response
        )
        expect(request).toHaveBeenCalledWith({
            method: 'GET',
            path: `${configPath}/trial_comparison_result/`,
            query: { comparison_id: comparisonId },
        })

        const poll = tool.schema.parse({
            id: scoutId,
            comparison_id: comparisonId,
            fields: ['status', 'error', 'evaluation.status', 'evaluation.report.outcome'],
        })
        expect(await tool.handler(context, poll)).toEqual({
            status: 'completed',
            error: null,
            evaluation: { status: 'completed', report: { outcome: response.evaluation.report.outcome } },
        })
        expect(request).toHaveBeenLastCalledWith({
            method: 'GET',
            path: `${configPath}/trial_comparison_result/`,
            query: { comparison_id: comparisonId },
        })

        const beforeEvaluation = { ...response, status: 'running', evaluation: null }
        request.mockResolvedValue(beforeEvaluation)
        expect(await tool.handler(context, poll)).toEqual({ status: 'running', error: null })
        expect(await tool.handler(context, tool.schema.parse({ id: scoutId, comparison_id: comparisonId }))).toEqual(
            beforeEvaluation
        )
    })

    it('preserves archived-history filters and the cursor envelope', async () => {
        const cursor = `0000000000000000001-${comparisonId}.json`
        const response = {
            results: [{ comparison_id: comparisonId, archived: true }],
            has_more: true,
            next_cursor: cursor,
        }
        const { context, request } = createContext(response)
        const tool = GENERATED_TOOLS['scout-trial-list']!()
        const query = { include_archived: true, limit: 2, cursor }

        expect(await tool.handler(context, tool.schema.parse({ id: scoutId, ...query }))).toEqual(response)
        expect(request).toHaveBeenCalledWith({ method: 'GET', path: `${configPath}/trial_comparison_history/`, query })
    })

    it.each([
        { name: 'scout-trial-resume', action: 'trial_comparison_resume', body: { comparison_id: comparisonId } },
        {
            name: 'scout-trial-archive',
            action: 'trial_comparison_archive',
            body: { comparison_id: comparisonId, archived: true },
        },
        {
            name: 'scout-trial-archive',
            action: 'trial_comparison_archive',
            body: { comparison_id: comparisonId, archived: false },
        },
    ])('$name addresses the existing trial: $body', async ({ name, action, body }) => {
        const { context, request } = createContext({ comparison_id: comparisonId })
        const tool = GENERATED_TOOLS[name]!()

        await tool.handler(context, tool.schema.parse({ id: scoutId, ...body }))

        expect(request).toHaveBeenCalledWith({ method: 'POST', path: `${configPath}/${action}/`, body })
    })
})
