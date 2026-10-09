import { describe, expect, it } from 'vitest'

import { buildPathsView, MAX_EDGES } from '../../src/ui-apps/components/pathsView'
import type { PathsResultItem } from '../../src/ui-apps/components/types'

function edge(step: number, from: string, to: string, value: number): PathsResultItem {
    return { source: `${step}_${from}`, target: `${step + 1}_${to}`, value }
}

describe('buildPathsView', () => {
    it('draws only the busiest transitions but counts steps on the full result', () => {
        const busy = Array.from({ length: MAX_EDGES }, (_, i) => edge(1, '/home', `/page-${i}`, 100 + i))
        const quietDeepStep = edge(6, '/checkout', '/thanks', 1)

        const view = buildPathsView([quietDeepStep, ...busy])

        expect(view.truncated).toBe(true)
        expect(view.edges).toHaveLength(MAX_EDGES)
        expect(view.edges).not.toContainEqual(quietDeepStep)
        expect(view.edges[0]?.value).toBe(100 + MAX_EDGES - 1)
        expect(view.stepCount).toBe(7)
    })

    it.each([
        { name: 'fits five steps in the frame', steps: 4, chartWidth: '100%', pinned: true },
        { name: 'scrolls past five steps', steps: 9, chartWidth: '180%', pinned: true },
        { name: 'caps the scroll width for a very long path', steps: 40, chartWidth: '500%', pinned: false },
    ])('$name', ({ steps, chartWidth, pinned }) => {
        const chain = Array.from({ length: steps - 1 }, (_, i) => edge(i + 1, `/p${i}`, `/p${i + 1}`, 10))

        const view = buildPathsView(chain)

        expect(view.chartWidth).toBe(chartWidth)
        expect(view.graph.stepsPinned).toBe(pinned)
        expect(view.columnLabels).toHaveLength(pinned ? steps : 0)
    })

    it('returns an empty view for a non-array result', () => {
        expect(buildPathsView(undefined)).toMatchObject({ allEdges: [], edges: [], truncated: false, stepCount: 0 })
    })
})
