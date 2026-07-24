import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { ReadonlyRunSurface } from './ReadonlyRunSurface'

// Stand in for the heavy impl chunk so the test exercises the lazy/Suspense wiring, not the real surface.
jest.mock('./ReadonlyRunSurfaceImpl', () => ({ __esModule: true, default: () => <div data-attr="thread" /> }))
jest.mock('./RunLogSkeleton', () => ({ RunLogSkeleton: () => <div data-attr="run-log-skeleton" /> }))

describe('ReadonlyRunSurface', () => {
    afterEach(() => {
        cleanup()
    })

    it('lazy-loads behind the run-log skeleton, then renders the thread', async () => {
        render(<ReadonlyRunSurface taskId="task-1" runId="run-1" interaction="read-only" />)
        // The Suspense fallback shows the shared skeleton while the impl chunk resolves...
        expect(screen.getByTestId('run-log-skeleton')).toBeInTheDocument()
        // ...then the lazily-imported surface mounts and the thread appears.
        expect(await screen.findByTestId('thread')).toBeInTheDocument()
    })
})
