import { strToU8, zipSync } from 'fflate'
import { createServer, type Server } from 'node:http'
import type { AddressInfo } from 'node:net'

// Boot downloads this archive from the agent-skills-latest GitHub release, which is
// republished by deleting the asset and uploading its replacement, so the URL 404s
// during a publish. A miss costs `SkillCatalogService.warmup` a 60s retry budget,
// which is longer than the `beforeAll` budget of every suite that boots the app.
const SKILL_ARCHIVE = zipSync({
    'integration-harness/SKILL.md': strToU8(
        [
            '---',
            'name: integration-harness',
            'description: Placeholder skill so the harness boots without reaching the network.',
            '---',
            '',
            '# integration-harness',
            '',
            'Stands in for the published skill bundle.',
            '',
        ].join('\n')
    ),
})

export type ArchiveServer = {
    url: string
    stop: () => Promise<void>
}

// Boot also downloads the context-mill resources archive from a GitHub release. The
// resource catalog tests need at least one posthog:// resource with a readable body.
const CONTEXT_MILL_ARCHIVE = zipSync({
    'manifest.json': strToU8(
        JSON.stringify({
            version: '1.0',
            resources: [
                {
                    id: 'integration-harness-doc',
                    name: 'Integration harness doc',
                    uri: 'posthog://integration-harness/doc',
                    file: 'integration-harness/doc.md',
                    resource: {
                        mimeType: 'text/markdown',
                        description: 'Placeholder resource so the harness boots without reaching the network.',
                        text: '# integration-harness doc',
                    },
                },
            ],
        })
    ),
    'integration-harness/doc.md': strToU8('# integration-harness doc\n'),
})

async function startArchiveServer(archive: Uint8Array, fileName: string): Promise<ArchiveServer> {
    const server: Server = createServer((_request, response) => {
        response.writeHead(200, { 'content-type': 'application/zip' })
        response.end(Buffer.from(archive))
    })
    // A failed bind emits `error` instead of calling the listen callback, so without
    // this listener the promise never settles and node ends the worker before the
    // caller can release what it already opened.
    await new Promise<void>((resolve, reject) => {
        const onError = (err: Error): void => reject(err)
        server.once('error', onError)
        server.listen(0, '127.0.0.1', () => {
            server.off('error', onError)
            resolve()
        })
    })
    const { port } = server.address() as AddressInfo

    return {
        url: `http://127.0.0.1:${port}/${fileName}`,
        stop: () => new Promise<void>((resolve) => server.close(() => resolve())),
    }
}

export function startSkillArchiveServer(): Promise<ArchiveServer> {
    return startArchiveServer(SKILL_ARCHIVE, 'skills.zip')
}

export function startContextMillArchiveServer(): Promise<ArchiveServer> {
    return startArchiveServer(CONTEXT_MILL_ARCHIVE, 'skills-mcp-resources.zip')
}
