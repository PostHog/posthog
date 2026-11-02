import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import { InstructionsBuilder } from '@/hono/instructions'
import { makeSkillFile, SkillCatalog } from '@/skills/skill-catalog'
import { ASK_POSTHOG_HOW_INSTRUCTIONS, buildRecipe } from '@/tools/ask-posthog-how'
import type { Tool, ZodObjectAny } from '@/tools/types'

import { makeToolExecutorState } from '../shared/test-utils'

function tool(
    name: string,
    description: string,
    readOnly: boolean,
    schema: ZodObjectAny = z.object({})
): Tool<ZodObjectAny> {
    return {
        name,
        title: name,
        description,
        schema,
        scopes: [],
        annotations: {
            readOnlyHint: readOnly,
            destructiveHint: !readOnly,
            idempotentHint: readOnly,
            openWorldHint: true,
        },
        handler: async () => ({}),
    }
}

const TOOLS = [
    tool(
        'dashboard-get',
        'Get a dashboard and its tiles.',
        true,
        z.object({ id: z.number(), refresh: z.boolean().optional() })
    ),
    tool('activity-feed', 'What is running now: variants, experiments, and launches.', true),
    tool('experiment-list', 'List experiments.', true),
    tool('experiment-end', 'End a running experiment and ship a variant.', false, z.object({ id: z.number() })),
    tool('survey-list', 'List surveys and their questions.', true),
]

const SKILLS = new SkillCatalog([
    {
        name: 'exploring-experiments',
        description: 'Find experiments and read their variants and results.',
        files: [makeSkillFile('SKILL.md', '---\nname: exploring-experiments\ndescription: x\n---\nExperiments.')],
    },
    {
        name: 'creating-surveys',
        description: 'Create a survey.',
        files: [makeSkillFile('SKILL.md', '---\nname: creating-surveys\ndescription: x\n---\nSurveys.')],
    },
])

describe('ask-posthog-how', () => {
    it.each([
        {
            intent: 'Which experiments are running now, and what variants do they have?',
            first: 'experiment-list',
            excluded: 'experiment-end',
        },
        {
            intent: 'End the running experiment and ship the winning variant',
            first: 'experiment-end',
            excluded: undefined,
        },
    ])('offers write tools only when the goal asks for a change: $intent', ({ intent, first, excluded }) => {
        const tools = buildRecipe(intent, TOOLS).steps.map((step) => step.tool)

        expect(tools[0]).toBe(first)
        if (excluded) {
            expect(tools).not.toContain(excluded)
        }
    })

    it('spells out the required arguments in the exec command', () => {
        expect(buildRecipe('Show me the dashboard', TOOLS).steps[0]).toMatchObject({
            tool: 'dashboard-get',
            required_arguments: ['id'],
            exec: 'call dashboard-get {"id":"<id>"}',
        })
    })

    it('recommends the skills that match the goal', () => {
        const recipe = buildRecipe('Which experiments are running, and what variants do they have?', TOOLS, SKILLS)

        expect(recipe.skills.map((skill) => skill.name)).toEqual(['exploring-experiments'])
    })

    it.each([
        { surface: 'ask' as const, slim: true },
        { surface: 'mcp' as const, slim: false },
    ])('keeps the full instructions off the ask surface: $surface', ({ surface, slim }) => {
        const state = makeToolExecutorState([], { useSingleExec: true, surface })

        expect(new InstructionsBuilder('Full guidelines.').build(state) === ASK_POSTHOG_HOW_INSTRUCTIONS).toBe(slim)
    })
})
