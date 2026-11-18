/**
 * The story-to-file map of a Storybook build.
 *
 * Visual Review reads it to find the file each snapshot's story lives in, and from that the team
 * that owns the snapshot. The map is uploaded once per distinct content, so it has to serialize to
 * the same bytes every time the same build is read.
 */
import { createHash } from 'node:crypto'
import { posix } from 'node:path'

export interface StoryIndexMap {
    content: Buffer
    hash: string
    storyCount: number
}

type StorybookIndex = { entries?: Record<string, { type?: string; importPath?: string }> }

/**
 * Build the map from a Storybook `index.json`.
 *
 * Storybook writes each `importPath` relative to the directory it ran in, so paths resolve against
 * `storybookRoot`, given relative to the repository root. A story imported from outside the
 * checkout has no repository path, so no team can own it, and it is left out.
 */
export function buildStoryIndex(indexJson: string, storybookRoot: string): StoryIndexMap {
    const document = JSON.parse(indexJson) as StorybookIndex
    const entries = document.entries ?? {}
    const root = posix.normalize(storybookRoot.replaceAll('\\', '/'))

    const paths: Record<string, string> = {}
    // Sorted, so the same build always serializes to the same bytes and so to the same hash.
    for (const storyId of Object.keys(entries).sort()) {
        const entry = entries[storyId]
        // Docs pages carry an importPath too, and no snapshot is taken of one.
        if (entry?.type !== 'story' || typeof entry.importPath !== 'string' || !entry.importPath) {
            continue
        }
        if (posix.isAbsolute(entry.importPath)) {
            continue
        }
        const path = posix.normalize(posix.join(root, entry.importPath))
        if (path === '..' || path.startsWith('../')) {
            continue
        }
        paths[storyId] = path
    }

    const content = Buffer.from(JSON.stringify({ version: 1, paths }))
    return {
        content,
        hash: createHash('sha256').update(content).digest('hex'),
        storyCount: Object.keys(paths).length,
    }
}
