import { describe, expect, it, vi } from 'vitest'

import { GENERATED_TOOL_MAP } from '@/tools/generated'
import getProjectsTool from '@/tools/projects/getProjects'
import type { Context } from '@/tools/types'

const ORG_ID = 'org-1'

// A project row as the API returns it, with the public write key and secret
// tokens a discovery response must never carry into the model context.
const PROJECT_WITH_CREDENTIALS = {
    id: 42,
    name: 'My project',
    organization: ORG_ID,
    api_token: 'phc_public_write_key',
    secret_api_token: 'phs_secret',
    secret_api_token_backup: 'phs_secret_backup',
    live_events_token: 'live_token',
}

const CREDENTIAL_VALUES = ['phc_public_write_key', 'phs_secret', 'phs_secret_backup', 'live_token']

describe('project discovery does not expose credentials', () => {
    it('projects-get strips credentials from every listed project', async () => {
        const context = {
            stateManager: { getOrgID: vi.fn().mockResolvedValue(ORG_ID) },
            api: {
                organizations: () => ({
                    projects: () => ({
                        list: vi.fn().mockResolvedValue({ success: true, data: [PROJECT_WITH_CREDENTIALS] }),
                    }),
                }),
            },
        } as unknown as Context

        const projects = await getProjectsTool().handler(context, {})

        expect(projects).toHaveLength(1)
        expect(projects[0]!.id).toBe(42)
        const serialized = JSON.stringify(projects)
        for (const value of CREDENTIAL_VALUES) {
            expect(serialized).not.toContain(value)
        }
    })

    it('project-get strips credentials from the returned project', async () => {
        const context = {
            stateManager: {
                getOrgID: vi.fn().mockResolvedValue(ORG_ID),
                getProjectId: vi.fn().mockResolvedValue(42),
            },
            api: { request: vi.fn().mockResolvedValue(PROJECT_WITH_CREDENTIALS) },
        } as unknown as Context

        const project = await GENERATED_TOOL_MAP['project-get']!().handler(context, {})

        expect((project as { id: number }).id).toBe(42)
        const serialized = JSON.stringify(project)
        for (const value of CREDENTIAL_VALUES) {
            expect(serialized).not.toContain(value)
        }
    })
})
