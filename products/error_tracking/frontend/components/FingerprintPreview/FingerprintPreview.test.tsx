import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'

import { PropertyOperator } from '~/types'

import { FingerprintPreview } from './FingerprintPreview'
import { ManageFingerprintsModal } from './ManageFingerprintsModal'

// jsdom ships no PointerEvent, and quill's Base UI checkbox constructs one from the owning
// window on click, which throws inside the library before its onCheckedChange runs. Defined here
// rather than in jest.polyfills.js because components feature-detect window.PointerEvent to pick
// between their pointer and legacy-mouse paths, so a global definition changes what other suites
// exercise.
if (typeof window.PointerEvent !== 'function') {
    class TestPointerEvent extends window.MouseEvent {
        readonly pointerId: number
        readonly pointerType: string
        readonly isPrimary: boolean
        constructor(type: string, params: PointerEventInit = {}) {
            super(type, params)
            this.pointerId = params.pointerId ?? 0
            this.pointerType = params.pointerType ?? ''
            this.isPrimary = params.isPrimary ?? false
        }
    }
    window.PointerEvent = TestPointerEvent as unknown as typeof PointerEvent
}

const mockUseActions = jest.fn()
const mockUseFeatureFlag = jest.fn()
const mockUseValues = jest.fn()

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useActions: (...args: unknown[]) => mockUseActions(...args),
    useValues: (...args: unknown[]) => mockUseValues(...args),
}))

jest.mock('lib/hooks/useFeatureFlag', () => ({
    useFeatureFlag: (...args: unknown[]) => mockUseFeatureFlag(...args),
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
    manageOpen?: boolean
    selected?: string[]
    unmergeDisabledReason?: string | null
    activeFingerprint?: string | null
    activeEventError?: string | null
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
    manageOpen = false,
    selected = [],
    unmergeDisabledReason = null,
    activeFingerprint = null,
    activeEventError = null,
}: RenderPreviewOptions = {}): {
    applyPropertyFilter: jest.Mock
    loadProjection: jest.Mock
    setFingerprintsViewMode: jest.Mock
    openSimilar: jest.Mock
    openManage: jest.Mock
    toggleFingerprint: jest.Mock
    unmergeSelected: jest.Mock
    setActiveFingerprint: jest.Mock
    retryActiveEvent: jest.Mock
} {
    const loadProjection = jest.fn()
    const applyPropertyFilter = jest.fn()
    const setFingerprintsViewMode = jest.fn()
    const openSimilar = jest.fn()
    const openManage = jest.fn()
    const toggleFingerprint = jest.fn()
    const unmergeSelected = jest.fn()
    const setActiveFingerprint = jest.fn()
    const retryActiveEvent = jest.fn()

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
        isOpen: manageOpen,
        selected,
        unmerging: false,
        unmergeDisabledReason,
        activeFingerprint,
        activeEvent: null,
        activeEventLoading: false,
        activeEventError,
    })
    mockUseActions.mockReturnValue({
        loadProjection,
        applyPropertyFilter,
        setFingerprintsViewMode,
        openSimilar,
        closeSimilar: jest.fn(),
        openManage,
        closeManage: jest.fn(),
        toggleFingerprint,
        unmergeSelected,
        setActiveFingerprint,
        retryActiveEvent,
    })

    render(
        <>
            <FingerprintPreview issueId={ISSUE_ID} />
            <ManageFingerprintsModal issueId={ISSUE_ID} />
        </>
    )

    return {
        applyPropertyFilter,
        loadProjection,
        setFingerprintsViewMode,
        openSimilar,
        openManage,
        toggleFingerprint,
        unmergeSelected,
        setActiveFingerprint,
        retryActiveEvent,
    }
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
        mockUseFeatureFlag.mockReset()
        mockUseFeatureFlag.mockReturnValue(true)
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

    it('opens the manage modal from the header instead of leaving the issue', async () => {
        const user = userEvent.setup()
        const { openManage } = renderPreview()

        const manage = screen.getByText('Manage fingerprints')
        expect(manage.closest('a')).toBeNull()

        await user.click(manage)
        expect(openManage).toHaveBeenCalledTimes(1)
    })

    it('hides fingerprint management when issue splitting is disabled', () => {
        mockUseFeatureFlag.mockReturnValue(false)
        renderPreview()

        expect(screen.queryByText('Manage fingerprints')).not.toBeInTheDocument()
    })

    it('unmerges the fingerprints selected in the manage modal', async () => {
        const user = userEvent.setup()
        const { toggleFingerprint, unmergeSelected } = renderPreview({
            fingerprints: FINGERPRINTS,
            samples: SAMPLES,
            manageOpen: true,
            selected: ['fingerprint-one'],
        })

        // Only the modal renders checkboxes, so this is scoped to it without a role-name query.
        const [, secondRow] = screen.getAllByRole('checkbox')
        await user.click(secondRow)
        expect(toggleFingerprint).toHaveBeenCalledWith('fingerprint-two')

        await user.click(screen.getByText('Unmerge'))
        expect(unmergeSelected).toHaveBeenCalledTimes(1)
    })

    it('shows a retry action when the fingerprint sample cannot load', async () => {
        const user = userEvent.setup()
        const { retryActiveEvent } = renderPreview({
            fingerprints: FINGERPRINTS,
            samples: SAMPLES,
            manageOpen: true,
            activeFingerprint: 'fingerprint-one',
            activeEventError: 'Request failed',
        })

        expect(screen.getByText("Couldn't load a sample exception for this fingerprint.")).toBeInTheDocument()
        await user.click(screen.getByText('Retry'))
        expect(retryActiveEvent).toHaveBeenCalledTimes(1)
    })

    it('previews a fingerprint without changing the unmerge selection', async () => {
        const user = userEvent.setup()
        const { setActiveFingerprint, toggleFingerprint } = renderPreview({
            fingerprints: FINGERPRINTS,
            samples: SAMPLES,
            manageOpen: true,
        })

        // The row carries two targets: the checkbox picks what to unmerge, the label picks what to preview.
        const [, secondPreview] = screen.getAllByTestId('error-tracking-manage-fingerprint-preview')
        await user.click(secondPreview)

        expect(setActiveFingerprint).toHaveBeenCalledWith('fingerprint-two')
        expect(toggleFingerprint).not.toHaveBeenCalled()
    })
})
