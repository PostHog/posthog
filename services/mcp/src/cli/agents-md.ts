import * as fs from 'node:fs/promises'
import * as path from 'node:path'

import agentsMdPrompt from './agents-md-snippet.md'

export const AGENTS_MD_PROMPT = agentsMdPrompt.trim()
export const AGENTS_MD_SNIPPET = AGENTS_MD_PROMPT

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
    if (existing.includes(AGENTS_MD_SNIPPET)) {
        next = existing
    } else if (existing.trim()) {
        next = `${existing.trimEnd()}\n\n${AGENTS_MD_SNIPPET}\n`
    } else {
        next = `${AGENTS_MD_SNIPPET}\n`
    }

    await fs.mkdir(path.dirname(targetPath), { recursive: true })
    await fs.writeFile(targetPath, next)
    return targetPath
}
