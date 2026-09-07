import { strToU8, zipSync } from 'fflate'

import type { ContextMillManifest } from '@/resources/manifest-types'

// Stand-in for the `skills-mcp-resources.zip` asset that the context-mill
// GitHub release publishes. Invented content, shaped to exercise the three
// entry kinds the loader must handle:
//
//   - inline text with no backing file
//   - text backed by a file that the archive carries
//   - text backed by a file the archive does not carry, which
//     `filterValidEntries` must drop instead of serving
//
// Tests that need a real context-mill release must use the canary in
// `tests/canary/context-mill-release.test.ts`.

/** A fixture entry the server is expected to serve. */
export const CONTEXT_MILL_FIXTURE_SERVED_URI = 'posthog://fixture/inline-guide'

/** The fixture entry `filterValidEntries` must drop. */
export const CONTEXT_MILL_FIXTURE_ORPHANED_URI = 'posthog://fixture/orphaned-guide'

const FILED_GUIDE_PATH = 'skills/filed-guide.md'
const FILED_GUIDE_TEXT = '# Filed guide\n\nBacked by a file inside the archive.\n'

const MANIFEST: ContextMillManifest = {
    version: '1.0',
    resources: [
        {
            id: 'fixture-inline-guide',
            name: 'Fixture inline guide',
            uri: CONTEXT_MILL_FIXTURE_SERVED_URI,
            resource: {
                mimeType: 'text/markdown',
                description: 'Inline fixture resource with no backing file.',
                text: '# Inline guide\n\nServed straight from the manifest.\n',
            },
        },
        {
            id: 'fixture-filed-guide',
            name: 'Fixture filed guide',
            uri: 'posthog://fixture/filed-guide',
            file: FILED_GUIDE_PATH,
            resource: {
                mimeType: 'text/markdown',
                description: 'Fixture resource whose file the archive carries.',
                text: FILED_GUIDE_TEXT,
            },
        },
        {
            id: 'fixture-orphaned-guide',
            name: 'Fixture orphaned guide',
            uri: CONTEXT_MILL_FIXTURE_ORPHANED_URI,
            file: 'skills/absent-guide.md',
            resource: {
                mimeType: 'text/markdown',
                description: 'Fixture resource whose file the archive omits.',
                text: '# Orphaned guide\n\nNever served, because its file is missing.\n',
            },
        },
    ],
}

export function buildContextMillFixtureArchive(): Uint8Array {
    return zipSync({
        'manifest.json': strToU8(JSON.stringify(MANIFEST)),
        [FILED_GUIDE_PATH]: strToU8(FILED_GUIDE_TEXT),
    })
}
