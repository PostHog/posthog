import { strToU8, zipSync } from 'fflate'
import { createServer, type Server } from 'node:http'
import type { AddressInfo } from 'node:net'

import type { ContextMillManifest } from '@/resources/manifest-types'

// Stands in for the context-mill release archive the server fetches at warmup.
// Two entries so catalog tests can read one resource without the other, and one
// of them file-backed so `filterValidEntries` sees both shapes.
const SKILL_BODY = '# Test skill\n\nBody served from the fixture archive.\n'

const MANIFEST: ContextMillManifest = {
    version: '1.0',
    resources: [
        {
            id: 'fixture-skill',
            name: 'Fixture skill',
            uri: 'posthog://skills/fixture-skill',
            file: 'fixture-skill.md',
            resource: {
                mimeType: 'text/markdown',
                description: 'A file-backed fixture skill',
                text: SKILL_BODY,
            },
        },
        {
            id: 'fixture-inline',
            name: 'Fixture inline resource',
            uri: 'posthog://docs/fixture-inline',
            resource: {
                mimeType: 'text/markdown',
                description: 'An inline fixture resource',
                text: '# Inline fixture\n',
            },
        },
    ],
}

const ARCHIVE = zipSync({
    'manifest.json': strToU8(JSON.stringify(MANIFEST)),
    'fixture-skill.md': strToU8(SKILL_BODY),
})

export interface SkillsArchiveServer {
    url: string
    stop: () => Promise<void>
}

/**
 * Serves the fixture archive over loopback so the integration suite exercises
 * the real fetch/unzip/cache path without reaching the context-mill release on
 * github.com — an external dependency that drops connections often enough to
 * redden CI, and whose contents this repo does not control.
 */
export async function startSkillsArchiveServer(): Promise<SkillsArchiveServer> {
    const server: Server = createServer((_request, response) => {
        response.writeHead(200, { 'content-type': 'application/zip' })
        response.end(Buffer.from(ARCHIVE))
    })

    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', () => resolve()))
    const { port } = server.address() as AddressInfo

    return {
        url: `http://127.0.0.1:${port}/skills-mcp-resources.zip`,
        stop: () => new Promise<void>((resolve) => server.close(() => resolve())),
    }
}
