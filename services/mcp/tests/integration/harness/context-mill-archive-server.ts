import { createServer } from 'node:http'
import type { AddressInfo } from 'node:net'

import { buildContextMillFixtureArchive } from '../../fixtures/context-mill-archive'

export type ContextMillArchiveServer = {
    /** Value for `POSTHOG_MCP_LOCAL_SKILLS_URL`. */
    url: string
    stop: () => Promise<void>
}

/**
 * Serves the fixture resource archive over HTTP on a loopback port.
 *
 * The resource catalog otherwise downloads the archive from the context-mill
 * GitHub release on every cold start, which makes the whole MCP resource
 * surface depend on a third party being reachable and on whatever that release
 * currently contains.
 */
export async function startContextMillArchiveServer(): Promise<ContextMillArchiveServer> {
    const archive = buildContextMillFixtureArchive()
    const server = createServer((_req, res) => {
        res.writeHead(200, { 'content-type': 'application/zip' })
        res.end(archive)
    })
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
    const { port } = server.address() as AddressInfo

    return {
        url: `http://127.0.0.1:${port}/skills-mcp-resources.zip`,
        stop: () => new Promise<void>((resolve) => server.close(() => resolve())),
    }
}
