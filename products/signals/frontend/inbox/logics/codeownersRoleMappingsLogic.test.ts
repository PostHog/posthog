/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { OrganizationMembershipLevel } from 'lib/constants'
import { organizationLogic } from 'scenes/organizationLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { RoleExternalReferenceApi, SyncModeEnumApi } from 'products/integrations/frontend/generated/api.schemas'
import type { RoleApi } from 'products/platform_features/frontend/generated/api.schemas'
import type { CodeownersTeamsResponseApi } from 'products/signals/frontend/generated/api.schemas'

import {
    codeownersRoleMappingsLogic,
    mergeCodeownersMappingRows,
    parseCodeownersTeamInput,
} from './codeownersRoleMappingsLogic'

const CREATOR = {
    id: 1,
    uuid: '018f0000-0000-7000-8000-0000000000aa',
    distinct_id: 'admin-distinct-id',
    email: 'admin@posthog.com',
    first_name: 'Admin',
    hedgehog_config: null,
}

const DEVEX_ROLE: RoleApi = {
    id: '018f0000-0000-7000-8000-000000000101',
    name: 'Dev Ex',
    members: [],
    created_at: '2026-01-01T00:00:00Z',
    created_by: CREATOR,
    is_default: false,
}

const ERROR_TRACKING_ROLE: RoleApi = {
    id: '018f0000-0000-7000-8000-000000000102',
    name: 'Error Tracking',
    members: [],
    created_at: '2026-01-01T00:00:00Z',
    created_by: CREATOR,
    is_default: false,
}

function makeReference(
    id: string,
    slug: string | null,
    roleId: string,
    overrides: Partial<RoleExternalReferenceApi> = {}
): RoleExternalReferenceApi {
    return {
        id,
        provider: 'github',
        provider_organization_id: 'posthog',
        provider_role_id: slug ?? id,
        provider_role_slug: slug,
        provider_role_name: slug ? `@posthog/${slug}` : 'Legacy Team',
        role: roleId,
        sync_mode: 'manual' as SyncModeEnumApi,
        role_created_by_sync: false,
        orphaned_at: null,
        last_synced_at: '2026-01-01T00:00:00Z',
        drift: {
            has_drift: false,
            to_add_count: 0,
            to_remove_count: 0,
            provider_member_count: 2,
            matched_posthog_member_count: 2,
            current_role_member_count: 2,
        },
        created_at: '2026-01-01T00:00:00Z',
        created_by: CREATOR,
        ...overrides,
    }
}

const EXISTING_REF = makeReference('ref-1', 'team-cymbal', ERROR_TRACKING_ROLE.id, {
    sync_mode: 'proposed',
    drift: {
        has_drift: true,
        to_add_count: 1,
        to_remove_count: 0,
        provider_member_count: 3,
        matched_posthog_member_count: 3,
        current_role_member_count: 2,
    },
})
const SYNCED_REF = makeReference('ref-1', 'team-cymbal', ERROR_TRACKING_ROLE.id, {
    sync_mode: 'auto',
})
const CREATED_REF = makeReference('ref-2', 'team-devex', DEVEX_ROLE.id)
const UPDATED_REF = makeReference('ref-1', 'team-cymbal', DEVEX_ROLE.id)
const MANUAL_REF = makeReference('ref-3', 'team-manual', DEVEX_ROLE.id)

const SCAN_RESPONSE: CodeownersTeamsResponseApi = {
    teams: [
        {
            provider_organization_id: 'posthog',
            team_slug: 'team-cymbal',
            handle: '@posthog/team-cymbal',
            repositories: ['PostHog/posthog'],
            likely_role_id: ERROR_TRACKING_ROLE.id,
            likely_role_name: ERROR_TRACKING_ROLE.name,
            match_source: 'external_reference',
        },
        {
            provider_organization_id: 'posthog',
            team_slug: 'team-devex',
            handle: '@posthog/team-devex',
            repositories: ['PostHog/posthog'],
            likely_role_id: DEVEX_ROLE.id,
            likely_role_name: DEVEX_ROLE.name,
            match_source: 'name_match',
        },
    ],
    scanned_repository_count: 1,
    total_repository_count: 1,
}

describe('codeownersRoleMappingsLogic', () => {
    let logic: ReturnType<typeof codeownersRoleMappingsLogic.build> | undefined

    beforeEach(() => {
        initKeaTests()
        ;(posthog.capture as jest.Mock).mockClear()
        useMocks({
            get: {
                '/api/organizations/:organization_id/roles/': { count: 2, results: [DEVEX_ROLE, ERROR_TRACKING_ROLE] },
                '/api/organizations/:organization_id/role_external_references/': {
                    count: 1,
                    results: [EXISTING_REF],
                },
                '/api/projects/:team_id/signals/codeowners_teams/': SCAN_RESPONSE,
                '/api/projects/:team_id/integrations/': {
                    results: [{ id: 1, kind: 'github', display_name: 'PostHog', config: {} }],
                },
            },
            post: {
                '/api/organizations/:organization_id/role_external_references/': async ({ request }) => {
                    const body = (await request.json()) as { provider_role_slug?: string }
                    return [201, body.provider_role_slug === 'team-manual' ? MANUAL_REF : CREATED_REF]
                },
                '/api/organizations/:organization_id/role_external_references/sync_github/': [
                    200,
                    {
                        created_roles: 2,
                        updated_roles: 1,
                        proposed_roles: 1,
                        orphaned_references: 0,
                        skipped_missing_members_permission: false,
                    },
                ],
                '/api/organizations/:organization_id/role_external_references/:id/apply_sync/': [200, SYNCED_REF],
            },
            patch: {
                '/api/organizations/:organization_id/role_external_references/:id/': [200, UPDATED_REF],
            },
            delete: {
                '/api/organizations/:organization_id/role_external_references/:id/': [204, null],
            },
        })
        organizationLogic.mount()
        if (organizationLogic.values.currentOrganization) {
            organizationLogic.actions.loadCurrentOrganizationSuccess({
                ...organizationLogic.values.currentOrganization,
                membership_level: OrganizationMembershipLevel.Admin,
            })
        }
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('supports GitHub team sync, proposal confirmation, pin, update, clear, and manual add', async () => {
        logic = codeownersRoleMappingsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(posthog.capture).not.toHaveBeenCalledWith('Inbox settings changed', expect.anything(), expect.anything())

        const proposedCymbal = logic.values.rows.find((row) => row.teamSlug === 'team-cymbal')!
        expect(proposedCymbal.explicitReference?.sync_mode).toEqual('proposed')

        logic.actions.applyReferenceSync(proposedCymbal, 'auto')
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.rows.find((row) => row.teamSlug === 'team-cymbal')?.explicitReference?.sync_mode).toEqual(
            'auto'
        )
        expect(posthog.capture).toHaveBeenCalledWith(
            'Inbox settings changed',
            expect.objectContaining({ setting: 'github_role_sync_mode_updated', new_value: 'auto', success: true }),
            undefined
        )

        logic.actions.syncGithubTeams()
        await expectLogic(logic).toFinishAllListeners()
        expect(posthog.capture).toHaveBeenCalledWith(
            'Inbox settings changed',
            expect.objectContaining({ setting: 'github_roles_synced', new_value: 4, success: true }),
            undefined
        )

        const devexRow = logic.values.rows.find((row) => row.teamSlug === 'team-devex')!
        logic.actions.setTeamRole(devexRow, DEVEX_ROLE.id)
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.rows.find((row) => row.teamSlug === 'team-devex')?.selectedRoleId).toEqual(DEVEX_ROLE.id)

        const cymbalRow = logic.values.rows.find((row) => row.teamSlug === 'team-cymbal')!
        logic.actions.setTeamRole(cymbalRow, DEVEX_ROLE.id)
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.rows.find((row) => row.teamSlug === 'team-cymbal')?.selectedRoleId).toEqual(DEVEX_ROLE.id)

        const updatedCymbalRow = logic.values.rows.find((row) => row.teamSlug === 'team-cymbal')!
        logic.actions.setTeamRole(updatedCymbalRow, null)
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.rows.find((row) => row.teamSlug === 'team-cymbal')?.selectedRoleId).toBeNull()

        logic.actions.setDraftTeamHandle('@PostHog/team-manual')
        logic.actions.setDraftRoleId(DEVEX_ROLE.id)
        logic.actions.addManualMapping()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.rows.find((row) => row.teamSlug === 'team-manual')?.selectedRoleId).toEqual(DEVEX_ROLE.id)
    })

    it('keeps orphaned references separate from active references that reuse the same slug', () => {
        const active = makeReference('ref-active', 'team-platform', DEVEX_ROLE.id, { sync_mode: 'auto' })
        const orphaned = makeReference('ref-orphaned', null, ERROR_TRACKING_ROLE.id, {
            provider_role_name: 'team-platform',
            orphaned_at: '2026-02-01T00:00:00Z',
        })
        const rows = mergeCodeownersMappingRows([], [active, orphaned])
        expect(rows.map((row) => row.key)).toEqual(['posthog/team-platform', 'orphaned:ref-orphaned'])
    })

    it.each([
        [
            '@PostHog/Team-DevEx',
            null,
            { providerOrganizationId: 'posthog', teamSlug: 'team-devex', handle: '@posthog/team-devex' },
        ],
        [
            'posthog/team-devex',
            null,
            { providerOrganizationId: 'posthog', teamSlug: 'team-devex', handle: '@posthog/team-devex' },
        ],
        [
            'team-devex',
            'PostHog',
            { providerOrganizationId: 'posthog', teamSlug: 'team-devex', handle: '@posthog/team-devex' },
        ],
        ['team-devex', null, null],
        ['owner@example.com', 'PostHog', null],
        ['@org/nested/slug', null, null],
    ])('parses CODEOWNERS team input (%s, defaultOrg=%s)', (input, defaultOrg, expected) => {
        expect(parseCodeownersTeamInput(input, defaultOrg)).toEqual(expected)
    })
})
