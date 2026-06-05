import * as fs from 'node:fs/promises'
import * as path from 'node:path'

import agentsMdPrompt from './agents-md-snippet.md'

const START_MARKER = '<!-- posthog-cli-api:start -->'
const END_MARKER = '<!-- posthog-cli-api:end -->'

export const AGENTS_MD_PROMPT = agentsMdPrompt.trim()
export const AGENTS_MD_SNIPPET = `${START_MARKER}\n${AGENTS_MD_PROMPT}\n${END_MARKER}`

function errorCode(error: unknown): unknown {
    return typeof error === 'object' && error !== null && 'code' in error
        ? (error as { code?: unknown }).code
        : undefined
}

export async function installAgentsMdSnippet(opts: { cwd?: string; filePath?: string } = {}): Promise<string> {
    const targetPath = path.resolve(opts.filePath ?? path.join(opts.cwd ?? process.cwd(), 'AGENTS.md'))
    let existing = ''
    try {
        existing = await fs.readFile(targetPath, 'utf-8')
    } catch (error) {
        if (errorCode(error) !== 'ENOENT') {
            throw error
        }
    }

    let next: string
    const start = existing.indexOf(START_MARKER)
    const end = existing.indexOf(END_MARKER)
    if (start !== -1 && end !== -1 && end > start) {
        next = `${existing.slice(0, start)}${AGENTS_MD_SNIPPET}${existing.slice(end + END_MARKER.length)}`
    } else if (existing.trim()) {
        next = `${existing.trimEnd()}\n\n${AGENTS_MD_SNIPPET}\n`
    } else {
        next = `${AGENTS_MD_SNIPPET}\n`
    }

    await fs.mkdir(path.dirname(targetPath), { recursive: true })
    await fs.writeFile(targetPath, next)
    return targetPath
}
