import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it, vi } from 'vitest'
import { parse as parseYaml } from 'yaml'

import { GENERATED_TOOL_MAP } from '@/tools/generated'
import getProjectsTool from '@/tools/projects/getProjects'
import type { Context } from '@/tools/types'

const ORG_ID = 'org-1'
const PROJECT_ID = 42

// `project-get` is the surface whose exclude list is reviewed when a secret is
// added to the project serializer. Deriving the fixture from it means a new
// secret there also has to be dropped by the other project surfaces, instead of
// leaking until someone notices the lists drifted apart.
const coreDefinitions = parseYaml(fs.readFileSync(path.resolve(__dirname, '../../definitions/core.yaml'), 'utf-8'))
const SECRET_FIELDS: string[] = (coreDefinitions.tools['project-get'].response.exclude as string[]).filter(
    (field) => field.includes('token') || field.includes('secret')
)

const secretValue = (field: string): string => `SECRET_VALUE_${field}`
const API_TOKEN = 'phc_public_write_key'

const PROJECT_WITH_CREDENTIALS = {
    id: PROJECT_ID,
    name: 'My project',
    organization: ORG_ID,
    api_token: API_TOKEN,
    ...Object.fromEntries(SECRET_FIELDS.map((field) => [field, secretValue(field)])),
}

function expectNoSecrets(payload: unknown): void {
    const serialized = JSON.stringify(payload)
    for (const field of SECRET_FIELDS) {
        expect(serialized).not.toContain(secretValue(field))
    }
}

describe('project tools do not expose credentials', () => {
    it('derives a non-empty secret set that excludes the public token', () => {
        expect(SECRET_FIELDS).toContain('secret_api_token')
        expect(SECRET_FIELDS).not.toContain('api_token')
    })

    it('projects-get strips secrets and the API token from every listed project', async () => {
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
        expect(projects[0]!.id).toBe(PROJECT_ID)
        expectNoSecrets(projects)
        expect(JSON.stringify(projects)).not.toContain(API_TOKEN)
    })

    it('project-get strips secrets but keeps the API token callers ask it for', async () => {
        const context = {
            stateManager: {
                getOrgID: vi.fn().mockResolvedValue(ORG_ID),
                getProjectId: vi.fn().mockResolvedValue(PROJECT_ID),
            },
            api: { request: vi.fn().mockResolvedValue(PROJECT_WITH_CREDENTIALS) },
        } as unknown as Context

        const project = await GENERATED_TOOL_MAP['project-get']!().handler(context, {})

        expect((project as { id: number }).id).toBe(PROJECT_ID)
        expectNoSecrets(project)
        // The setup wizard in products/tasks reads the public token from here;
        // it is the only tool that still returns it.
        expect((project as { api_token: string }).api_token).toBe(API_TOKEN)
    })

    it('project-settings-update strips secrets and the API token from the updated project', async () => {
        const context = {
            stateManager: { getOrgID: vi.fn().mockResolvedValue(ORG_ID) },
            api: { request: vi.fn().mockResolvedValue(PROJECT_WITH_CREDENTIALS) },
        } as unknown as Context

        const project = await GENERATED_TOOL_MAP['project-settings-update']!().handler(context, {
            id: PROJECT_ID,
            name: 'Renamed project',
        })

        expect((project as { id: number }).id).toBe(PROJECT_ID)
        expectNoSecrets(project)
        expect(JSON.stringify(project)).not.toContain(API_TOKEN)
    })
})
