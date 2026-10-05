#!/usr/bin/env node
import fs from 'node:fs'

import { clearSectionIfPresent, postSection } from '../../../frontend/bin/ci-report/update-ci-report.mjs'

const SECTION_ID = 'mcp-agent-api'
const [markdownPath] = process.argv.slice(2)

// No output file means the comparison never ran. Leave the report alone.
if (!markdownPath || !fs.existsSync(markdownPath)) {
    console.info('No agent API diff output - leaving the report unchanged.')
    process.exit(0)
}

const markdown = fs.readFileSync(markdownPath, 'utf-8').trim()

if (!markdown) {
    // A change that a later push reverted must not leave a stale table behind.
    await clearSectionIfPresent({
        id: SECTION_ID,
        summary: 'no agent API changes',
        body: 'This PR no longer changes the tools, params, scopes or annotations agents see.',
    })
    process.exit(0)
}

const overLimit = markdown.includes('**Input schema now over')
await postSection({
    id: SECTION_ID,
    status: overLimit ? 'warn' : 'info',
    summary: overLimit ? 'tool input schema over the Claude limit' : 'agent-facing tool changes',
    body: `What this PR changes for agents, from the tool schema snapshots and tool definitions.\n\n${markdown}`,
})
