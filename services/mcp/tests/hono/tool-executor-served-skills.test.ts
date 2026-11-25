import { beforeAll, describe, expect, it, vi } from 'vitest'

import { MCP_EXEC_SKILLS_FEATURE_FLAG, MCP_SERVED_SKILLS_LIST_FLAG } from '@/hono/constants'
import { InstructionsBuilder } from '@/hono/instructions'
import type { ResolvedState } from '@/hono/request-state-resolver'
import { ToolCatalog } from '@/hono/tool-catalog'
import { ToolExecutor } from '@/hono/tool-executor'
import { makeSkillFile, SkillCatalog } from '@/skills/skill-catalog'

import { makeToolExecutorState } from '../shared/test-utils'

// A fixture in place of the real list, so a change to a real skill's flag or consumers cannot break these cases.
const openSkill = 'open-skill'
const gatedSkill = 'gated-skill'
const gate = 'some-gate'
const scopedSkill = 'slack-skill'
const consumers = ['slack']

vi.mock('@/generated/served-skills.json', () => ({
    default: {
        skills: {
            'open-skill': { audience: 'customer' },
            'gated-skill': { audience: 'customer', feature_flag: 'some-gate' },
            'slack-skill': { audience: 'customer', consumers: ['slack'] },
        },
    },
}))

describe('ToolExecutor served skills', () => {
    let catalog: ToolCatalog

    beforeAll(async () => {
        catalog = new ToolCatalog()
        await catalog.warmup()
    })

    const unlistedSkill = 'internal-runbook'
    const skills = new SkillCatalog(
        [openSkill, gatedSkill, scopedSkill, unlistedSkill].map((name) => ({
            name,
            description: `The ${name} skill.`,
            files: [makeSkillFile('SKILL.md', `# ${name}`)],
        }))
    )
    const skillExecutor = (): ToolExecutor =>
        new ToolExecutor(catalog, new InstructionsBuilder(''), { getCatalog: () => skills } as any)
    const learn = async (
        command: string,
        state: ResolvedState
    ): Promise<{ content: { text: string }[]; isError?: boolean }> =>
        (await skillExecutor().handleToolCall({ name: 'exec', arguments: { command } }, state)) as any

    it.each([
        { label: 'an unlisted skill before the rollout', skill: unlistedSkill, rollout: false, served: true },
        { label: 'a listed skill', skill: openSkill, rollout: true, served: true },
        { label: 'an unlisted skill', skill: unlistedSkill, rollout: true, served: false },
        { label: 'a gated skill without its flag', skill: gatedSkill, rollout: true, served: false },
        { label: 'a gated skill with its flag', skill: gatedSkill, rollout: true, gateOn: true, served: true },
        { label: 'a consumer skill to another caller', skill: scopedSkill, rollout: true, served: false },
        {
            label: 'a consumer skill to its consumer',
            skill: scopedSkill,
            rollout: true,
            consumer: consumers[0],
            served: true,
        },
    ])('learn serves $label: $served', async ({ skill, rollout, gateOn, consumer, served }) => {
        const state = makeToolExecutorState([], {
            useSingleExec: true,
            toolFeatureFlags: {
                [MCP_EXEC_SKILLS_FEATURE_FLAG]: true,
                [MCP_SERVED_SKILLS_LIST_FLAG]: rollout,
                ...(gateOn ? { [gate]: true } : {}),
            },
            ...(consumer
                ? {
                      sessionContext: {
                          mcpClientName: 'claude-ai',
                          mcpClientVersion: '1.0',
                          mcpProtocolVersion: '2025-03-26',
                          mcpConsumer: consumer,
                          mcpVendorClient: undefined,
                      },
                  }
                : {}),
        })

        const read = await learn(`learn posthog:${skill}`, state)
        const search = await learn(`learn -s "${skill}"`, state)

        expect(read.content[0]!.text.includes(`# ${skill}`)).toBe(served)
        expect(read.content[0]!.text.includes('Unknown skill')).toBe(!served)
        expect(search.content[0]!.text.includes(`posthog:${skill}`)).toBe(served)
    })
})
