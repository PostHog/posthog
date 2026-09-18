import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'

import { PropertyOperator } from '~/types'

import { FingerprintPreview } from './FingerprintPreview'

const mockUseActions = jest.fn()
const mockUseValues = jest.fn()

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useActions: (...args: unknown[]) => mockUseActions(...args),
    useValues: (...args: unknown[]) => mockUseValues(...args),
}))

jest.mock('@posthog/quill-charts', () => ({
    ScatterChart: ({
        series,
        onPointClick,
        dataAttr,
    }: {
        series: { points: { meta?: { fingerprint?: string } }[] }[]
        onPointClick: (point: { meta?: { fingerprint?: string } }) => void
        dataAttr: string
    }) => (
        <button data-attr={dataAttr} onClick={() => onPointClick(series[0].points[0])}>
            Fingerprint map
        </button>
    ),
    TooltipSurface: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}))

jest.mock('lib/charts/hooks', () => ({
    useChartTheme: () => ({}),
}))

jest.mock('../IssueFilterPreview/IssueFilterPreviewHeader', () => ({
    IssueFilterPreviewHeader: ({ title, children }: { title: string; children?: ReactNode }) => (
        <header>
            <span>{title}</span>
            {children}
        </header>
    ),
}))

const ISSUE_ID = '01890a1b-2c3d-4e4f-8a9b-0c1d2e3f4a5b'

interface ProjectionPoint {
    fingerprint: string
    x: number
    y: number
}

interface RenderPreviewOptions {
    projectionLoading?: boolean
    projectionError?: string | null
    projectionResults?: ProjectionPoint[]
    fingerprints?: { fingerprint: string; created_at: string }[]
    fingerprintsLoading?: boolean
    samples?: Record<string, { type: string; value: string }>
    samplesLoading?: boolean
    viewMode?: 'list' | 'map'
}

function renderPreview({
    projectionLoading = false,
    projectionError = null,
    projectionResults = [],
    fingerprints = [],
    fingerprintsLoading = false,
    samples = {},
    samplesLoading = false,
    viewMode = 'list',
}: RenderPreviewOptions = {}): {
    applyPropertyFilter: jest.Mock
    loadProjection: jest.Mock
    setFingerprintsViewMode: jest.Mock
    openSimilar: jest.Mock
} {
    const loadProjection = jest.fn()
    const applyPropertyFilter = jest.fn()
    const setFingerprintsViewMode = jest.fn()
    const openSimilar = jest.fn()

    // Every consumer destructures the values it needs, so one bag serves each logic the tree binds.
    mockUseValues.mockReturnValue({
        fingerprintDomains: null,
        fingerprintSeries: [
            {
                key: 'fingerprints',
                label: 'Fingerprints',
                points: projectionResults.map(({ fingerprint, x, y }) => ({
                    x,
                    y,
                    label: fingerprint,
                    meta: { fingerprint },
                })),
            },
        ],
        projection: { results: projectionResults },
        projectionError,
        projectionLoading,
        issueFingerprints: fingerprints,
        issueFingerprintsLoading: fingerprintsLoading,
        samples,
        samplesLoading,
        fingerprintsViewMode: viewMode,
        timezone: 'UTC',
        originFingerprint: null,
        similar: [],
        similarLoading: false,
    })
    mockUseActions.mockReturnValue({
        loadProjection,
        applyPropertyFilter,
        setFingerprintsViewMode,
        openSimilar,
        closeSimilar: jest.fn(),
    })

    render(<FingerprintPreview issueId={ISSUE_ID} />)

    return { applyPropertyFilter, loadProjection, setFingerprintsViewMode, openSimilar }
}

const EMBEDDED = [{ fingerprint: 'embedded-fingerprint', x: 1, y: 2 }]
const FINGERPRINTS = [
    { fingerprint: 'fingerprint-one', created_at: '2026-08-27T10:30:00Z' },
    { fingerprint: 'fingerprint-two', created_at: '2026-09-01T08:00:00Z' },
]
const SAMPLES = {
    'fingerprint-one': { type: 'TypeError', value: "Cannot read property 'id' of undefined" },
    'fingerprint-two': { type: 'SyntaxError', value: 'Unexpected token' },
}

describe('FingerprintPreview', () => {
    beforeEach(() => {
        mockUseActions.mockReset()
        mockUseValues.mockReset()
    })

    afterEach(() => {
        cleanup()
    })

    it('previews each fingerprint by exception type and message, with its first seen date', async () => {
        const user = userEvent.setup()
        const { applyPropertyFilter } = renderPreview({ fingerprints: FINGERPRINTS, samples: SAMPLES })

        expect(screen.getByText('TypeError')).toBeInTheDocument()
        expect(screen.getByText("Cannot read property 'id' of undefined")).toBeInTheDocument()
        expect(screen.getByText('27 Aug 2026')).toBeInTheDocument()
        expect(screen.getByText('1 Sep 2026')).toBeInTheDocument()
        expect(screen.queryByText('fingerprint-one')).not.toBeInTheDocument()

        await user.click(screen.getByText('SyntaxError'))
        expect(applyPropertyFilter).toHaveBeenCalledWith(
            '$exception_fingerprint',
            'fingerprint-two',
            PropertyOperator.Exact,
            true
        )
    })

    it('falls back to the fingerprint when no sample exception is available', () => {
        renderPreview({ fingerprints: FINGERPRINTS, samples: { 'fingerprint-one': SAMPLES['fingerprint-one'] } })

        expect(screen.getByText('TypeError')).toBeInTheDocument()
        expect(screen.getByText('fingerprint-two')).toBeInTheDocument()
    })

    it('opens the similar fingerprints modal for the row it was clicked on', async () => {
        const user = userEvent.setup()
        const { openSimilar } = renderPreview({ fingerprints: FINGERPRINTS, samples: SAMPLES })

        await user.click(screen.getAllByLabelText('Find similar fingerprints')[1])
        expect(openSimilar).toHaveBeenCalledWith('fingerprint-two', '2026-09-01T08:00:00Z')
    })

    it('keeps the list loading state ahead of the empty state', () => {
        renderPreview({ samplesLoading: true })

        expect(screen.getByLabelText('Loading')).toBeInTheDocument()
        expect(screen.queryByText('No fingerprints found for this issue.')).not.toBeInTheDocument()
    })

    it('shows an empty state when the issue has no fingerprints', () => {
        renderPreview()

        expect(screen.getByText('No fingerprints found for this issue.')).toBeInTheDocument()
    })

    it('disables the map and stays on the list when the issue has no embeddings', async () => {
        const user = userEvent.setup()
        const { setFingerprintsViewMode } = renderPreview({ fingerprints: FINGERPRINTS, viewMode: 'map' })

        expect(screen.getByText('Map')).toHaveAttribute('aria-disabled', 'true')
        expect(screen.getByText('fingerprint-one')).toBeInTheDocument()
        // no samples supplied, so rows fall back to the fingerprint itself
        expect(screen.queryByText('Fingerprint map')).not.toBeInTheDocument()

        await user.click(screen.getByText('Map'))
        expect(setFingerprintsViewMode).not.toHaveBeenCalled()
    })

    it('shows the map and filters exceptions from a point when embeddings are available', async () => {
        const user = userEvent.setup()
        const { applyPropertyFilter } = renderPreview({
            projectionResults: EMBEDDED,
            fingerprints: FINGERPRINTS,
            viewMode: 'map',
        })

        await user.click(screen.getByText('Fingerprint map'))
        expect(applyPropertyFilter).toHaveBeenCalledWith(
            '$exception_fingerprint',
            'embedded-fingerprint',
            PropertyOperator.Exact,
            true
        )
    })

    it('switches view mode from the toggle', async () => {
        const user = userEvent.setup()
        const { setFingerprintsViewMode } = renderPreview({
            projectionResults: EMBEDDED,
            fingerprints: FINGERPRINTS,
        })

        await user.click(screen.getByText('Map'))
        expect(setFingerprintsViewMode).toHaveBeenCalledWith('map')
    })

    it('keeps the projection error and retry action in the map view', async () => {
        const user = userEvent.setup()
        const { loadProjection } = renderPreview({
            projectionError: 'Request failed',
            fingerprints: FINGERPRINTS,
            viewMode: 'map',
        })

        expect(screen.getByText("Couldn't load the fingerprint map.")).toBeInTheDocument()
        await user.click(screen.getByText('Retry'))
        expect(loadProjection).toHaveBeenCalledTimes(1)
    })

    it('links to fingerprint management for the current issue', () => {
        renderPreview()

        expect(screen.getByText('Manage fingerprints').closest('a')).toHaveAttribute(
            'href',
            `/error_tracking/${ISSUE_ID}/fingerprints`
        )
    })
})
