import { AgentSpec, AgentSpecSchema } from './spec'

describe('AgentSpecSchema', () => {
    it('parses a minimal spec with defaults', () => {
        const parsed = AgentSpecSchema.parse({ model: 'claude-opus-4-7' })
        expect(parsed.model).toBe('claude-opus-4-7')
        expect(parsed.triggers).toEqual([])
        expect(parsed.tools).toEqual([])
        expect(parsed.entrypoint).toBe('agent.md')
        expect(parsed.limits.max_turns).toBe(50)
    })

    it('parses a fully-populated spec', () => {
        const spec: AgentSpec = AgentSpecSchema.parse({
            model: 'claude-opus-4-7',
            triggers: [
                { type: 'slack', config: { channel_id: 'C01', mention_only: true, trusted_workspaces: '*' } },
                { type: 'webhook', config: { path: '/hook' } },
            ],
            tools: [
                { kind: 'native', id: '@posthog/query' },
                { kind: 'custom', id: 'fetch-acme', path: 'tools/fetch-acme/' },
            ],
            mcps: [{ kind: 'agent', slug: 'weekly-digest' }],
            skills: [{ id: 'deep-research', path: 'skills/deep-research/SKILL.md' }],
            integrations: ['slack:T01'],
            secrets: ['ACME_KEY'],
            limits: { max_turns: 10, max_tool_calls: 50, max_wall_seconds: 300 },
            entrypoint: 'agent.md',
        })
        expect(spec.triggers).toHaveLength(2)
        expect(spec.tools).toHaveLength(2)
        expect(spec.mcps[0]).toEqual({ kind: 'agent', slug: 'weekly-digest' })
    })

    it('rejects unknown trigger type', () => {
        expect(() =>
            AgentSpecSchema.parse({ model: 'x', triggers: [{ type: 'carrier-pigeon', config: {} }] })
        ).toThrow()
    })

    it('rejects unknown tool kind', () => {
        expect(() => AgentSpecSchema.parse({ model: 'x', tools: [{ kind: 'rogue', id: 'x' }] })).toThrow()
    })

    describe('framework_prompt config', () => {
        it('defaults to undefined when not present', () => {
            const spec = AgentSpecSchema.parse({ model: 'x' })
            expect(spec.framework_prompt).toBeUndefined()
        })

        it('parses an empty config with default omit list', () => {
            const spec = AgentSpecSchema.parse({ model: 'x', framework_prompt: {} })
            expect(spec.framework_prompt?.omit).toEqual([])
        })

        it('parses a populated omit list', () => {
            const spec = AgentSpecSchema.parse({
                model: 'x',
                framework_prompt: { omit: ['meta_tool_guidance', 'reasoning_hint'] },
            })
            expect(spec.framework_prompt?.omit).toEqual(['meta_tool_guidance', 'reasoning_hint'])
        })

        it('rejects unknown omit values', () => {
            expect(() =>
                AgentSpecSchema.parse({
                    model: 'x',
                    framework_prompt: { omit: ['unknown_section'] },
                })
            ).toThrow()
        })

        it('parses a version_pin', () => {
            const spec = AgentSpecSchema.parse({
                model: 'x',
                framework_prompt: { version_pin: 1 },
            })
            expect(spec.framework_prompt?.version_pin).toBe(1)
        })

        it('rejects negative version_pin', () => {
            expect(() =>
                AgentSpecSchema.parse({
                    model: 'x',
                    framework_prompt: { version_pin: 0 },
                })
            ).toThrow()
        })
    })

    describe('approval-gated tools', () => {
        it('defaults tools to requires_approval: false with admin-only policy', () => {
            const spec = AgentSpecSchema.parse({
                model: 'x',
                tools: [{ kind: 'native', id: '@posthog/query' }],
            })
            const t = spec.tools[0]
            // Narrow off the new `kind: "client"` variant; this test
            // covers native/custom approval defaults.
            if (t.kind === 'client') {
                throw new Error('expected native tool')
            }
            expect(t.requires_approval).toBe(false)
            expect(t.approval_policy.approvers).toEqual(['team_admins'])
            expect(t.approval_policy.allow_edit).toBe(false)
            expect(t.approval_policy.allow_agent_approver).toBe(false)
            expect(t.approval_policy.ttl_ms).toBe(24 * 60 * 60 * 1000)
        })

        it('parses requires_approval: true with overridden policy fields', () => {
            const spec = AgentSpecSchema.parse({
                model: 'x',
                tools: [
                    {
                        kind: 'native',
                        id: '@posthog/team-delete',
                        requires_approval: true,
                        approval_policy: { allow_edit: true, ttl_ms: 60 * 60 * 1000 },
                    },
                ],
            })
            const t = spec.tools[0]
            if (t.kind === 'client') {
                throw new Error('expected native tool')
            }
            expect(t.requires_approval).toBe(true)
            expect(t.approval_policy.allow_edit).toBe(true)
            expect(t.approval_policy.ttl_ms).toBe(60 * 60 * 1000)
            // unspecified fields still defaulted
            expect(t.approval_policy.approvers).toEqual(['team_admins'])
            expect(t.approval_policy.allow_agent_approver).toBe(false)
        })

        it('rejects ttl_ms below 1 minute', () => {
            expect(() =>
                AgentSpecSchema.parse({
                    model: 'x',
                    tools: [
                        {
                            kind: 'native',
                            id: '@posthog/team-delete',
                            requires_approval: true,
                            approval_policy: { ttl_ms: 30_000 },
                        },
                    ],
                })
            ).toThrow()
        })

        it('rejects ttl_ms above 7 days', () => {
            expect(() =>
                AgentSpecSchema.parse({
                    model: 'x',
                    tools: [
                        {
                            kind: 'native',
                            id: '@posthog/team-delete',
                            requires_approval: true,
                            approval_policy: { ttl_ms: 30 * 24 * 60 * 60 * 1000 },
                        },
                    ],
                })
            ).toThrow()
        })

        it('rejects empty approvers list', () => {
            expect(() =>
                AgentSpecSchema.parse({
                    model: 'x',
                    tools: [
                        {
                            kind: 'native',
                            id: '@posthog/team-delete',
                            requires_approval: true,
                            approval_policy: { approvers: [] },
                        },
                    ],
                })
            ).toThrow()
        })

        it('rejects approver scopes not yet supported in v0', () => {
            expect(() =>
                AgentSpecSchema.parse({
                    model: 'x',
                    tools: [
                        {
                            kind: 'native',
                            id: '@posthog/team-delete',
                            requires_approval: true,
                            approval_policy: { approvers: ['session_owner'] },
                        },
                    ],
                })
            ).toThrow()
        })
    })

    describe('resume config (per-agent TTL on completed sessions)', () => {
        it('defaults to undefined when not present (preserves today behaviour)', () => {
            const spec = AgentSpecSchema.parse({ model: 'x' })
            expect(spec.resume).toBeUndefined()
        })

        it('applies sensible defaults when an empty resume section is present', () => {
            const spec = AgentSpecSchema.parse({ model: 'x', resume: {} })
            expect(spec.resume?.enabled).toBe(false)
            expect(spec.resume?.max_completed_age_ms).toBe(7 * 24 * 60 * 60_000)
        })

        it('parses an opt-in week-long TTL config', () => {
            const spec = AgentSpecSchema.parse({
                model: 'x',
                resume: { enabled: true, max_completed_age_ms: 14 * 24 * 60 * 60_000 },
            })
            expect(spec.resume?.enabled).toBe(true)
            expect(spec.resume?.max_completed_age_ms).toBe(14 * 24 * 60 * 60_000)
        })

        it('rejects a non-positive max_completed_age_ms', () => {
            expect(() => AgentSpecSchema.parse({ model: 'x', resume: { max_completed_age_ms: 0 } })).toThrow()
        })
    })
})
