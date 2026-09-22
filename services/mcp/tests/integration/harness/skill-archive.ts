import { strToU8, zipSync } from 'fflate'
import { createServer, type Server } from 'node:http'
import type { AddressInfo } from 'node:net'

// Boot downloads this archive from the agent-skills-latest GitHub release, which is
// republished by deleting the asset and uploading its replacement, so the URL 404s
// during a publish. A miss costs `SkillCatalogService.warmup` a 60s retry budget,
// which is longer than the `beforeAll` budget of every suite that boots the app.
const ARCHIVE = zipSync({
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

export type SkillArchiveServer = {
    url: string
    stop: () => Promise<void>
}

export async function startSkillArchiveServer(): Promise<SkillArchiveServer> {
    const server: Server = createServer((_request, response) => {
        response.writeHead(200, { 'content-type': 'application/zip' })
        response.end(Buffer.from(ARCHIVE))
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
        url: `http://127.0.0.1:${port}/skills.zip`,
        stop: () => new Promise<void>((resolve) => server.close(() => resolve())),
    }
}
