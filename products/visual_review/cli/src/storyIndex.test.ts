import { describe, expect, it } from 'vitest'

import { buildStoryIndex } from './storyIndex.js'

function indexJson(entries: Record<string, { type: string; importPath: string }>): string {
    return JSON.stringify({ v: 5, entries })
}

describe('buildStoryIndex', () => {
    it('resolves each story against the Storybook directory and leaves out what no team can own', () => {
        const map = buildStoryIndex(
            indexJson({
                'scenes-app-button--primary': {
                    type: 'story',
                    importPath: '../../frontend/src/scenes/Button.stories.tsx',
                },
                'scenes-app-button--docs': { type: 'docs', importPath: '../../frontend/src/scenes/Button.mdx' },
                'outside--story': { type: 'story', importPath: '../../../elsewhere/Outside.stories.tsx' },
                'absolute--story': { type: 'story', importPath: '/tmp/Absolute.stories.tsx' },
            }),
            'common/storybook'
        )

        expect(JSON.parse(map.content.toString())).toEqual({
            version: 1,
            paths: { 'scenes-app-button--primary': 'frontend/src/scenes/Button.stories.tsx' },
        })
        expect(map.storyCount).toBe(1)
    })

    it('hashes the same build to the same value whatever order the index lists it in', () => {
        const button = { type: 'story', importPath: './src/Button.stories.tsx' }
        const card = { type: 'story', importPath: './src/Card.stories.tsx' }

        const first = buildStoryIndex(indexJson({ 'button--primary': button, 'card--primary': card }), '.')
        const second = buildStoryIndex(indexJson({ 'card--primary': card, 'button--primary': button }), '.')

        expect(second.hash).toBe(first.hash)
        expect(first.hash).toMatch(/^[0-9a-f]{64}$/)
    })
})
