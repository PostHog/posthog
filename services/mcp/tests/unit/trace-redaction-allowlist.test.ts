import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

import { RETAINED_AI_PROPERTIES } from '@/lib/trace-redaction'

// `core-filter-definitions-by-group.json` is generated from
// `posthog/taxonomy/taxonomy.py` and CI fails when the two disagree, so it is a
// stable stand-in for the taxonomy inside a TypeScript test.
const TAXONOMY_JSON = path.resolve(
    path.dirname(fileURLToPath(import.meta.url)),
    '../../../../frontend/src/taxonomy/core-filter-definitions-by-group.json'
)

describe('retained AI property allowlist', () => {
    it('holds exactly the $ai_ event properties the taxonomy defines', () => {
        const taxonomy = JSON.parse(readFileSync(TAXONOMY_JSON, 'utf8')) as {
            event_properties: Record<string, unknown>
        }
        const defined = Object.keys(taxonomy.event_properties)
            .filter((name) => name.startsWith('$ai_'))
            .sort()

        // A property the taxonomy gained is withheld from trace responses until
        // it is added here; one it dropped is stale. Both are fixed by editing
        // RETAINED_AI_PROPERTIES in src/lib/trace-redaction.ts.
        expect([...RETAINED_AI_PROPERTIES].sort()).toEqual(defined)
    })
})
