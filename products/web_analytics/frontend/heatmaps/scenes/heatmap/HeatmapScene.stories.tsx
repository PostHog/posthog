import { Meta, StoryObj } from '@storybook/react'
import { useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import type { MockSignature, Mocks } from '~/mocks/utils'

import { pageHistoryLogic } from '../../history/pageHistoryLogic'
import { heatmapLogic } from './heatmapLogic'

const generatingSaved = {
    id: 100,
    short_id: 'hm_gen',
    name: 'Generating…',
    url: 'https://example.com',
    data_url: 'https://example.com',
    target_widths: [768, 1024],
    type: 'screenshot',
    status: 'processing',
    has_content: false,
    snapshots: [],
    deleted: false,
    created_by: { id: 1, uuid: 'user-1', distinct_id: 'd1', first_name: 'Alice', email: 'alice@ph.com' },
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    exception: null,
    user_access_level: 'editor',
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Heatmap',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        pageUrl: urls.heatmap('hm_gen'),
        testOptions: {
            waitForLoadersToDisappear: true,
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/heatmap_screenshot/settings/': {
                    allowed_hostnames: [],
                    has_secret: false,
                    cookie_delivery_enabled: true,
                },
                '/api/projects/:team_id/saved/hm_gen/': generatingSaved,
                '/api/projects/:team_id/heatmap_screenshots/:id/content/': () => [202, generatingSaved],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const Generating: Story = {
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
}

const makeIframeSaved = (): Record<string, unknown> => ({
    id: 101,
    short_id: 'hm_iframe',
    name: 'Iframe example.com',
    url: `${window.location.origin}/mock-page.html`,
    data_url: `${window.location.origin}/mock-page.html`,
    target_widths: [],
    type: 'iframe',
    status: 'completed',
    has_content: false,
    snapshots: [],
    deleted: false,
    created_by: { id: 1, uuid: 'user-1', distinct_id: 'd1', first_name: 'Alice', email: 'alice@ph.com' },
    created_at: '2024-01-03T00:00:00Z',
    updated_at: '2024-01-03T00:00:00Z',
    exception: null,
    user_access_level: 'editor',
})

const iframeDecorators = [
    mswDecorator({
        get: {
            '/api/projects/:team_id/saved/hm_iframe/': () => [200, makeIframeSaved()],
            '/api/projects/:team_id/heatmaps/': () => [
                200,
                {
                    results: [
                        { pointer_relative_x: 0.4, pointer_target_fixed: false, pointer_y: 355, count: 85 },
                        { pointer_relative_x: 0.7, pointer_target_fixed: false, pointer_y: 24, count: 32 },
                        { pointer_relative_x: 0.77, pointer_target_fixed: false, pointer_y: 24, count: 28 },
                        { pointer_relative_x: 0.84, pointer_target_fixed: false, pointer_y: 24, count: 15 },
                        { pointer_relative_x: 0.91, pointer_target_fixed: false, pointer_y: 24, count: 12 },
                        { pointer_relative_x: 0.1, pointer_target_fixed: false, pointer_y: 24, count: 18 },
                        { pointer_relative_x: 0.17, pointer_target_fixed: false, pointer_y: 1150, count: 22 },
                        { pointer_relative_x: 0.5, pointer_target_fixed: false, pointer_y: 1150, count: 19 },
                        { pointer_relative_x: 0.83, pointer_target_fixed: false, pointer_y: 1150, count: 14 },
                    ],
                    count: 9,
                    next: null,
                    previous: null,
                },
            ],
        },
    }),
]

export const IframeExample: Story = {
    parameters: {
        pageUrl: urls.heatmap('hm_iframe'),
        testOptions: {
            // Wait for heatmap canvas to be ready with data loaded
            waitForSelector: '.heatmaps-ready',
            waitForLoadersToDisappear: true,
            // The overlay is 800px tall until the heatmap data arrives, then grows to fit the lowest
            // point. The app shell fixes its own height before the fetch resolves, so at the default
            // 720px viewport the page height depended on which of the two won the race. A viewport at
            // least as tall as the loaded overlay makes both states resolve to the same height.
            viewport: { width: 1280, height: 1300 },
        },
    },
    decorators: iframeDecorators,
}

export const IframeExampleWithEventFilter: Story = {
    parameters: {
        ...IframeExample.parameters,
        featureFlags: [FEATURE_FLAGS.HEATMAPS_EVENT_FILTER],
    },
    decorators: IframeExample.decorators,
}

export const New: Story = {
    parameters: {
        pageUrl: urls.heatmap('new'),
    },
}

type HeatmapLogicInstance = ReturnType<typeof heatmapLogic>

function AfterLoad({ run }: { run: (logic: HeatmapLogicInstance) => void }): JSX.Element {
    const logic = heatmapLogic({ id: 'hm_iframe' })
    const { savedSettings, loading } = useValues(logic)
    const configured = useRef(false)
    useEffect(() => {
        if (savedSettings && !loading && !configured.current) {
            configured.current = true
            run(logic)
        }
    }, [savedSettings, loading, logic, run])
    return <App />
}

function Narrow({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="[&_main]:max-w-[520px]">{children}</div>
}

const renameHeatmap = (logic: HeatmapLogicInstance): void => logic.actions.setName('Product page interactions')
const renameAndSave = (logic: HeatmapLogicInstance): void => {
    renameHeatmap(logic)
    logic.actions.updateHeatmap()
}
const iframeSavedPatch = (patch: MockSignature): Mocks => ({
    patch: { '/api/projects/:team_id/saved/hm_iframe/': patch },
})

const loadedViewport = { width: 1280, height: 1300 }
const loadedNarrowViewport = { width: 1280, height: 1700 }
const unsavedChangesTestOptions = {
    waitForSelector: ['.heatmaps-ready', '[data-attr="heatmap-save"]'],
    viewport: loadedViewport,
}
const pageSettingsDialogTestOptions = {
    waitForSelector: ['.heatmaps-ready', '[data-attr="heatmap-page-settings-content"]'],
    viewport: loadedViewport,
}

export const UnsavedChanges: Story = {
    ...IframeExample,
    parameters: {
        ...IframeExample.parameters,
        testOptions: unsavedChangesTestOptions,
    },
    render: () => <AfterLoad run={renameHeatmap} />,
}

export const UnsavedChangesNarrow: Story = {
    ...UnsavedChanges,
    parameters: {
        ...UnsavedChanges.parameters,
        testOptions: { ...unsavedChangesTestOptions, viewport: loadedNarrowViewport },
    },
    render: () => (
        <Narrow>
            <AfterLoad run={renameHeatmap} />
        </Narrow>
    ),
}

export const Saving: Story = {
    ...UnsavedChanges,
    parameters: {
        ...UnsavedChanges.parameters,
        testOptions: {
            waitForLoadersToDisappear: false,
            waitForSelector: ['.heatmaps-ready', '[data-attr="heatmap-save"][aria-disabled="true"]'],
            viewport: loadedViewport,
        },
    },
    decorators: [...iframeDecorators, mswDecorator(iframeSavedPatch(() => new Promise(() => {})))],
    render: () => <AfterLoad run={renameAndSave} />,
}

export const SaveFailed: Story = {
    ...UnsavedChanges,
    decorators: [
        ...iframeDecorators,
        mswDecorator(iframeSavedPatch(() => [500, { detail: 'Could not save heatmap. Try again.' }])),
    ],
    render: () => <AfterLoad run={renameAndSave} />,
}

export const SavedSuccessfully: Story = {
    ...UnsavedChanges,
    parameters: { ...IframeExample.parameters },
    decorators: [
        ...iframeDecorators,
        mswDecorator(
            iframeSavedPatch(async ({ request }: { request: Request }) => ({
                ...makeIframeSaved(),
                ...((await request.json()) as object),
            }))
        ),
    ],
    render: () => <AfterLoad run={renameAndSave} />,
}

const blockedPreviewDecorators = [
    ...iframeDecorators,
    mswDecorator({
        post: {
            '/api/projects/:team_id/saved/preflight/': {
                framing: 'blocked',
                blocked_by: 'content_security_policy',
                http_status: 200,
                body_excerpt: null,
            },
        },
        get: {
            '/api/projects/:team_id/heatmaps/': { results: [], count: 0, next: null, previous: null },
        },
    }),
]

export const BlockedPreview: Story = {
    ...IframeExample,
    parameters: {
        ...IframeExample.parameters,
        testOptions: { waitForSelector: '[data-attr="heatmap-preview-error"]', viewport: { width: 1280, height: 900 } },
    },
    decorators: blockedPreviewDecorators,
}

export const BlockedPreviewNarrow: Story = {
    ...BlockedPreview,
    render: () => (
        <Narrow>
            <App />
        </Narrow>
    ),
}

export const SwitchedToScreenshot: Story = {
    ...BlockedPreview,
    parameters: {
        ...BlockedPreview.parameters,
        testOptions: {
            waitForLoadersToDisappear: false,
            waitForSelector: '[data-attr="heatmap-generating-screenshot"]',
        },
    },
    decorators: [
        ...blockedPreviewDecorators,
        mswDecorator({
            patch: { '/api/projects/:team_id/saved/hm_iframe/': () => ({ ...makeIframeSaved(), type: 'screenshot' }) },
            post: {
                '/api/projects/:team_id/saved/hm_iframe/regenerate/': () => ({
                    ...makeIframeSaved(),
                    type: 'screenshot',
                    status: 'processing',
                }),
            },
            get: { '/api/projects/:team_id/saved/hm_iframe/': () => ({ ...makeIframeSaved(), status: 'processing' }) },
        }),
    ],
    render: () => <AfterLoad run={(logic) => logic.actions.switchToScreenshot()} />,
}

const openPageSettings = (logic: HeatmapLogicInstance): void => {
    logic.actions.setType('screenshot')
    logic.actions.openPageSettings()
}

export const PageSettingsDialog: Story = {
    ...IframeExample,
    parameters: {
        ...IframeExample.parameters,
        testOptions: pageSettingsDialogTestOptions,
    },
    render: () => <AfterLoad run={openPageSettings} />,
}

export const PageSettingsDialogNarrow: Story = {
    ...PageSettingsDialog,
    parameters: {
        ...PageSettingsDialog.parameters,
        testOptions: { ...pageSettingsDialogTestOptions, viewport: loadedNarrowViewport },
    },
    render: () => (
        <Narrow>
            <AfterLoad run={openPageSettings} />
        </Narrow>
    ),
}

const emptyHeatmapMocks = (queryResults: (query: string) => unknown[]): Mocks => ({
    get: {
        '/api/projects/:team_id/saved/hm_iframe/': () => [200, makeIframeSaved()],
        '/api/projects/:team_id/heatmaps/': () => [200, { results: [], count: 0, next: null, previous: null }],
    },
    post: {
        '/api/projects/:team_id/query/:query_kind/': async (info) => {
            const body = JSON.stringify(await info.request.clone().json())
            return [200, { results: queryResults(body) }]
        },
    },
})

const emptyHeatmapParameters = (waitForSelector: string): Story['parameters'] => ({
    ...IframeExample.parameters,
    testOptions: { ...IframeExample.parameters?.testOptions, waitForSelector },
})

export const EmptyWithDataAtAnotherWidth: Story = {
    parameters: emptyHeatmapParameters('[data-attr="heatmap-empty-show-width"]'),
    decorators: [
        mswDecorator(
            emptyHeatmapMocks((query) =>
                query.includes('GROUP BY type, width')
                    ? [
                          ['click', 390, 60],
                          ['click', 400, 30],
                      ]
                    : []
            )
        ),
    ],
}

export const EmptyWithSimilarUrls: Story = {
    parameters: emptyHeatmapParameters('[data-attr="heatmap-empty-similar-url"]'),
    decorators: [
        mswDecorator(
            emptyHeatmapMocks((query) =>
                query.includes('GROUP BY current_url')
                    ? [
                          [`${window.location.origin}/mock-page.html?utm_source=newsletter`, 42],
                          [`${window.location.origin}/mock-page.html/pricing`, 9],
                      ]
                    : query.includes('countIf')
                      ? [[0, 0]]
                      : []
            )
        ),
    ],
}

const historyScreenshot = (label: string): string => {
    const newer = label.includes('Current') || Number(label.slice(-2)) >= 19
    const title = newer ? 'New collection' : 'Weekly offers'
    const textX = newer ? 540 : 90
    const circleX = newer ? 240 : 780
    return `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1000"><rect width="1024" height="1000" fill="white"/><text x="50" y="55" font-family="sans-serif" font-size="24" fill="#252525">MarketDemo</text><text x="780" y="55" font-family="sans-serif" font-size="16" fill="#555">Shop · Offers</text><rect x="50" y="105" width="924" height="260" rx="8" fill="${newer ? '#efdfc8' : '#e0eedc'}"/><text x="${textX}" y="185" font-family="sans-serif" font-size="38" fill="#252525">${title}</text><text x="${textX}" y="225" font-family="sans-serif" font-size="18" fill="#555">${label}</text><rect x="${textX}" y="265" width="190" height="48" rx="4" fill="${newer ? '#734821' : '#245b32'}"/><text x="${textX + 18}" y="295" font-family="sans-serif" font-size="17" fill="white">Explore collection</text><circle cx="${circleX}" cy="235" r="80" fill="${newer ? '#ae997b' : '#86a870'}"/><rect x="50" y="400" width="290" height="280" rx="8" fill="#eeeDE5"/><rect x="367" y="400" width="290" height="280" rx="8" fill="#eeeDE5"/><rect x="684" y="400" width="290" height="280" rx="8" fill="#eeeDE5"/><text x="70" y="640" font-family="sans-serif" font-size="20" fill="#252525">Seasonal favourites</text><text x="385" y="640" font-family="sans-serif" font-size="20" fill="#252525">Everyday essentials</text><text x="703" y="640" font-family="sans-serif" font-size="20" fill="#252525">Something different</text></svg>`)}`
}
const historySaved = {
    ...generatingSaved,
    id: 102,
    short_id: 'hm_history',
    name: 'Home page',
    source: 'server',
    status: 'completed',
    has_content: true,
    target_widths: [1024],
    snapshots: [{ width: 1024, has_content: true }],
}
const historyCaptures = Array.from({ length: 21 }, (_, index) => {
    const date = `2024-01-${String(index + 1).padStart(2, '0')}`
    const failed = index === 17
    return {
        id: `cap-${index + 1}`,
        captured_on: date,
        captured_at: `${date}T02:40:00Z`,
        width: 1024,
        timezone: 'UTC',
        day_start: `${date}T00:00:00Z`,
        day_end: `2024-01-${String(index + 2).padStart(2, '0')}T00:00:00Z`,
        expires_at: '2024-04-01T00:00:00Z',
        revision: `capture-${index}`,
        latest_request: null,
        thumbnail_url: failed ? null : historyScreenshot(date),
        trigger: index === 19 ? 'manual' : 'scheduled',
        status: failed ? 'failed' : 'ok',
        failure_cause: failed ? 'page_http_status' : null,
        page_status: failed ? 503 : 200,
        content_url: failed ? null : historyScreenshot(date),
    }
})
const pageHistoryDecorators = [
    mswDecorator({
        get: {
            '/api/projects/:team_id/saved': { results: [historySaved], count: 1 },
            '/api/projects/:team_id/saved/hm_history/': historySaved,
            '/api/projects/:team_id/saved/hm_history/screenshot_history/': {
                width: 1024,
                retention_days: 90,
                storage_available: true,
                results: historyCaptures,
            },
            '/api/projects/:team_id/heatmaps/': {
                results: [
                    { pointer_relative_x: 0.2, pointer_target_fixed: false, pointer_y: 380, count: 64 },
                    { pointer_relative_x: 0.5, pointer_target_fixed: false, pointer_y: 380, count: 41 },
                    { pointer_relative_x: 0.8, pointer_target_fixed: false, pointer_y: 380, count: 27 },
                ],
                count: 3,
                next: null,
                previous: null,
            },
        },
    }),
]
export const PageHistory: Story = {
    parameters: {
        pageUrl: urls.heatmap('hm_history'),
        featureFlags: [FEATURE_FLAGS.HEATMAPS_PAGE_HISTORY],
        mockDate: '2024-01-21T12:00:00Z',
        testOptions: { waitForLoadersToDisappear: false },
    },
    decorators: pageHistoryDecorators,
    render: () => <HistoryAfterLoad />,
}

function HistoryAfterLoad({
    initialCapture,
    browserOpen = false,
}: {
    initialCapture?: string
    browserOpen?: boolean
}): JSX.Element {
    const scene = heatmapLogic({ id: 'hm_history' })
    const { savedSettings, loading } = useValues(scene)
    const historyLogic = pageHistoryLogic({ id: 'hm_history' })
    const { history } = useValues(historyLogic)
    const configured = useRef(false)
    useEffect(() => {
        if (savedSettings && !loading && !configured.current) {
            configured.current = true
            scene.actions.setScreenshotUrl(historyScreenshot('Current view'))
        }
    }, [savedSettings, loading, scene])
    const selected = useRef(false)
    useEffect(() => {
        if (history && !selected.current && initialCapture) {
            selected.current = true
            historyLogic.actions.selectCapture(initialCapture)
            if (browserOpen) {
                historyLogic.actions.setHistoryExpanded(true)
            }
        }
    }, [browserOpen, history, historyLogic, initialCapture])
    return <App />
}

export const HistoricalDay: Story = { ...PageHistory, render: () => <HistoryAfterLoad initialCapture="cap-17" /> }
export const HistoricalDayNarrow: Story = {
    ...HistoricalDay,
    decorators: [
        ...pageHistoryDecorators,
        (Story) => (
            <Narrow>
                <Story />
            </Narrow>
        ),
    ],
    parameters: {
        ...PageHistory.parameters,
        testOptions: { waitForLoadersToDisappear: true, viewport: loadedNarrowViewport },
    },
}

export const PageHistoryBrowser: Story = {
    ...HistoricalDay,
    render: () => <HistoryAfterLoad initialCapture="cap-17" browserOpen />,
}

export const PageHistoryBrowserNarrow: Story = {
    ...HistoricalDayNarrow,
    render: () => <HistoryAfterLoad initialCapture="cap-17" browserOpen />,
}
