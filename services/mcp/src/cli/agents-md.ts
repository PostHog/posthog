import * as fs from 'node:fs/promises'
import * as path from 'node:path'

import agentsMdPrompt from './agents-md-snippet.md'
import { assertResolvesInside, errorCode } from './utils'

const OPEN_TAG = '<posthog>'
const CLOSE_TAG = '</posthog>'

export const AGENTS_MD_PROMPT = agentsMdPrompt.trim()
/** The installed block is wrapped in XML tags so agents see a clearly delimited
 *  section and reinstalls can replace stale content in place. */
export const AGENTS_MD_SNIPPET = `${OPEN_TAG}\n${AGENTS_MD_PROMPT}\n${CLOSE_TAG}`

const MANAGED_BLOCK_PATTERN = /<posthog>[\s\S]*?<\/posthog>/

export async function installAgentsMdSnippet(opts: { cwd?: string; filePath?: string } = {}): Promise<string> {
    const cwd = opts.cwd ?? process.cwd()
    const targetPath = path.resolve(opts.filePath ?? path.join(cwd, 'AGENTS.md'))
    if (!opts.filePath) {
        await assertResolvesInside(cwd, targetPath, '. Pass --path to choose the file to update.')
    }
    let existing = ''
    try {
        existing = await fs.readFile(targetPath, 'utf-8')
    } catch (error) {
        if (errorCode(error) !== 'ENOENT') {
            throw error
        }
    }

    let next: string
    if (MANAGED_BLOCK_PATTERN.test(existing)) {
        next = existing.replace(MANAGED_BLOCK_PATTERN, () => AGENTS_MD_SNIPPET)
    } else if (existing.trim()) {
        next = `${existing.trimEnd()}\n\n${AGENTS_MD_SNIPPET}\n`
    } else {
        next = `${AGENTS_MD_SNIPPET}\n`
    }

    await fs.mkdir(path.dirname(targetPath), { recursive: true })
    await fs.writeFile(targetPath, next)
    return targetPath
}
