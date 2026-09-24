import { describe, expect, it } from 'vitest'

import { type ProjectCreationOrgFields, resolveProjectCreationBlock } from '@/lib/project-creation'

const team = (projectId: number, isDemo = false): { project_id: number; is_demo: boolean } => ({
    project_id: projectId,
    is_demo: isDemo,
})

const org = (overrides: ProjectCreationOrgFields = {}): ProjectCreationOrgFields => ({
    available_product_features: [{ key: 'organizations_projects', limit: 5 }],
    teams: [team(1)],
    membership_level: 8,
    members_can_create_projects: false,
    ...overrides,
})

describe('resolveProjectCreationBlock', () => {
    it('allows an admin with plan headroom', () => {
        expect(resolveProjectCreationBlock({ org: org(), scopedTeams: [] })).toBeUndefined()
    })

    it.each([
        ['no projects entitlement and one project in use', { available_product_features: [], teams: [team(1)] }],
        [
            'the plan allowance already in use',
            { available_product_features: [{ key: 'organizations_projects', limit: 2 }], teams: [team(1), team(2)] },
        ],
    ])('reports the plan limit with %s', (_name, overrides: ProjectCreationOrgFields) => {
        const block = resolveProjectCreationBlock({ org: org(overrides), scopedTeams: [] })

        expect(block).toContain('upgrade')
    })

    it.each([
        ['several environments of one project', [team(1), team(1)]],
        ['a demo project', [team(1), team(2, true)]],
    ])('counts %s as one project against the allowance', (_name, teams) => {
        const overrides = { available_product_features: [{ key: 'organizations_projects', limit: 2 }], teams }

        expect(resolveProjectCreationBlock({ org: org(overrides), scopedTeams: [] })).toBeUndefined()
    })

    it.each([
        ['with plan headroom', {}],
        ['in an organization at its plan limit', { available_product_features: [], teams: [team(1)] }],
    ])('reports the admin requirement for a member %s', (_name, overrides: ProjectCreationOrgFields) => {
        const block = resolveProjectCreationBlock({ org: org({ membership_level: 1, ...overrides }), scopedTeams: [] })

        expect(block).toContain('admins')
        expect(block).not.toContain('upgrade')
    })

    it('allows a member when the organization lets members create projects', () => {
        const overrides = {
            membership_level: 1,
            members_can_create_projects: true,
            available_product_features: [
                { key: 'organizations_projects', limit: 5 },
                { key: 'organization_invite_settings' },
            ],
        }

        expect(resolveProjectCreationBlock({ org: org(overrides), scopedTeams: [] })).toBeUndefined()
    })

    it('reports project-scoped credentials before reading the organization', () => {
        const block = resolveProjectCreationBlock({ org: undefined, scopedTeams: [42] })

        expect(block).toContain('organization-level')
    })

    it.each([
        ['the organization is unknown', undefined],
        ['the organization carries no team list', org({ teams: null, membership_level: null })],
    ])('stays silent when %s', (_name, orgFields: ProjectCreationOrgFields | undefined) => {
        expect(resolveProjectCreationBlock({ org: orgFields, scopedTeams: [] })).toBeUndefined()
    })
})
