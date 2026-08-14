import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { VisionActionApi } from '../generated/api.schemas'
import { scannerDigestLogic } from './scannerDigestLogic'

const DIGEST = {
    id: 'd1',
    name: 'Daily digest: my-scanner',
    scanner: 's1',
    enabled: true,
    is_scanner_digest: true,
    mode: 'group_summary',
    trigger_config: { rrule: 'FREQ=DAILY;BYHOUR=8;BYMINUTE=0', timezone: 'UTC' },
    delivery_config: [],
} as unknown as VisionActionApi

const OTHER_SUMMARY = {
    id: 'a1',
    name: 'slack summary',
    scanner: 's1',
    enabled: true,
    is_scanner_digest: false,
    mode: 'group_summary',
    trigger_config: { rrule: 'FREQ=DAILY' },
    delivery_config: [],
} as unknown as VisionActionApi

const ALERT = {
    id: 'al1',
    name: 'checkout alert',
    scanner: 's1',
    enabled: true,
    is_scanner_digest: false,
    mode: 'alert',
    trigger_config: { rrule: 'FREQ=HOURLY' },
    delivery_config: [],
} as unknown as VisionActionApi

const RUNS = [
    { id: 'r-skip', status: 'skipped', scheduled_at: '2026-01-02T08:00:00Z', observation_count: 0 },
    { id: 'r-done', status: 'completed', scheduled_at: '2026-01-01T08:00:00Z', observation_count: 4 },
]

describe('scannerDigestLogic', () => {
    let logic: ReturnType<typeof scannerDigestLogic.build>

    const mocksFor = (actions: VisionActionApi[]): Parameters<typeof useMocks>[0] => ({
        get: {
            '/api/projects/:team/vision/actions/': { results: actions, count: actions.length },
            '/api/projects/:team/vision/actions/:action/runs/': { results: RUNS, count: RUNS.length },
            '/api/projects/:team/vision/actions/:action/runs/:run/': {
                ...RUNS[1],
                synthesized_markdown: '## What happened\nUsers struggled with checkout.',
            },
            '/api/projects/:team/vision/actions/:action/run_preview/': {
                observation_count: 4,
                window_start: '2026-07-01T00:00:00Z',
                window_end: '2026-08-01T00:00:00Z',
                tiers: [
                    {
                        key: 'standard',
                        max_observations: 100,
                        covered_count: 4,
                        llm_calls: 1,
                        estimated_credits: 1,
                    },
                    { key: 'deep', max_observations: 500, covered_count: 4, llm_calls: 1, estimated_credits: 1 },
                    {
                        key: 'complete',
                        max_observations: 2000,
                        covered_count: 4,
                        llm_calls: 1,
                        estimated_credits: 1,
                    },
                ],
            },
        },
        post: {
            '/api/projects/:team/vision/actions/': () => [201, { ...DIGEST, id: 'd-new' }],
        },
    })

    const mountLogic = (): void => {
        initKeaTests()
        logic = scannerDigestLogic({ scannerId: 's1', scannerName: 'my-scanner' })
        logic.mount()
    }

    afterEach(() => logic.unmount())

    it('picks the digest among the scanner summaries and loads its newest completed run', async () => {
        // The lookback must skip non-completed runs (they carry no report) and a non-digest summary
        // must never claim the hero card.
        useMocks(mocksFor([OTHER_SUMMARY, DIGEST]))
        mountLogic()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.digest?.id).toEqual('d1')
        expect(logic.values.latestRun?.id).toEqual('r-done')
        expect(logic.values.latestRun?.synthesized_markdown).toContain('checkout')
        expect(logic.values.latestRunLoading).toEqual(false)
    })

    it('settles into the opt-in state when the scanner has no digest', async () => {
        useMocks(mocksFor([OTHER_SUMMARY]))
        mountLogic()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.digest).toBeNull()
        expect(logic.values.latestRun).toBeNull()
        // Stuck-true here means the card renders nothing instead of the "turn on" entrypoint.
        expect(logic.values.latestRunLoading).toEqual(false)
    })

    it('one-click create sends the digest marker and defaults, then settles without a card flash', async () => {
        useMocks(mocksFor([]))
        mountLogic()
        await expectLogic(logic).toFinishAllListeners()
        let body: any = null
        useMocks({
            post: {
                '/api/projects/:team/vision/actions/': async ({ request }) => {
                    body = await request.json()
                    return [201, { ...DIGEST, id: 'd-new' }]
                },
            },
        })
        // Optimistic insert + local run resolution instead of a refetch: refetching would blank the
        // card (digest absent while the list reloads, then latestRunLoading true) and flash it.
        await expectLogic(logic, () => {
            logic.actions.createDigest()
        })
            .toDispatchActions(['createDigestSuccess', 'addAction', 'loadLatestRunSuccess'])
            .toFinishAllListeners()
        expect(body).toMatchObject({
            name: 'Daily digest: my-scanner',
            scanner: 's1',
            is_scanner_digest: true,
            trigger_config: { rrule: 'FREQ=DAILY;BYHOUR=8;BYMINUTE=0' },
            delivery_config: [],
        })
        // The card renders the created digest immediately (no null-rendering gap).
        expect(logic.values.digest?.id).toEqual('d-new')
        expect(logic.values.latestRunLoading).toEqual(false)
    })

    it('offers only non-digest group summaries as promotion candidates', async () => {
        // Alerts don't produce a renderable summary, and the current digest isn't its own candidate.
        useMocks(mocksFor([DIGEST, OTHER_SUMMARY, ALERT]))
        mountLogic()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.promotableSummaries.map((a) => a.id)).toEqual(['a1'])
    })

    it('promoteDigest flags the chosen summary and reloads the list', async () => {
        useMocks(mocksFor([OTHER_SUMMARY]))
        mountLogic()
        await expectLogic(logic).toFinishAllListeners()
        let body: any = null
        useMocks({
            patch: {
                '/api/projects/:team/vision/actions/:action/': async ({ request }) => {
                    body = await request.json()
                    return [200, { ...OTHER_SUMMARY, is_scanner_digest: true }]
                },
            },
        })
        await expectLogic(logic, () => {
            logic.actions.promoteDigest('a1')
        })
            .toDispatchActions(['promoteDigestSuccess', 'loadActions'])
            .toFinishAllListeners()
        expect(body).toEqual({ is_scanner_digest: true })
    })

    it('runNow posts to the digest run endpoint and clears its loading state', async () => {
        useMocks(mocksFor([DIGEST]))
        mountLogic()
        await expectLogic(logic).toFinishAllListeners()
        let posted = false
        useMocks({
            post: {
                '/api/projects/:team/vision/actions/:action/run/': ({ request }: { request: Request }) => {
                    // Runs the digest itself (d1), not some other action.
                    expect(request.url).toContain('/vision/actions/d1/run/')
                    posted = true
                    return [202, { workflow_id: 'wf-1', already_running: false }]
                },
            },
        })
        await expectLogic(logic, () => logic.actions.runNow()).toFinishAllListeners()
        expect(posted).toBe(true)
        expect(logic.values.runningNow).toBe(false)
    })

    it('summarizePeriod posts the resolved window and closes the modal on success', async () => {
        useMocks(mocksFor([DIGEST]))
        mountLogic()
        await expectLogic(logic).toFinishAllListeners()
        let body: any = null
        useMocks({
            post: {
                '/api/projects/:team/vision/actions/:action/run/': async ({ request }: { request: Request }) => {
                    body = await request.json()
                    return [202, { workflow_id: 'wf-1', already_running: false }]
                },
            },
        })
        await expectLogic(logic, () => {
            logic.actions.openPeriodModal()
            logic.actions.setPeriodRange('-7d', null)
            logic.actions.summarizePeriod()
        })
            .toDispatchActions(['summarizePeriodDone'])
            .toFinishAllListeners()
        // The DateFilter tokens must reach the API as concrete ISO instants; the backend takes no
        // tokens. '-7d' anchors at the start of that day (relative_date_parse semantics), so pin the
        // ballpark rather than an exact offset.
        const dayMs = 24 * 60 * 60 * 1000
        expect(Date.parse(body.window_start)).toBeGreaterThan(Date.now() - 8 * dayMs)
        expect(Date.parse(body.window_start)).toBeLessThan(Date.now() - 6 * dayMs)
        expect(Date.parse(body.window_end)).toBeCloseTo(Date.now(), -4)
        expect(logic.values.periodModalOpen).toBe(false)
        expect(logic.values.summarizingPeriod).toBe(false)
    })

    it('loads the coverage preview for the picked range and submits the picked tier cap', async () => {
        // The tier picker quotes counts and costs straight off this preview, and the picked tier's
        // cap must reach the run body — dropping it silently shrinks a deep run back to the default.
        useMocks(mocksFor([DIGEST]))
        mountLogic()
        await expectLogic(logic).toFinishAllListeners()
        let runBody: any = null
        useMocks({
            get: {
                '/api/projects/:team/vision/actions/:action/run_preview/': () => [
                    200,
                    {
                        observation_count: 623,
                        window_start: '2026-07-01T00:00:00Z',
                        window_end: '2026-08-01T00:00:00Z',
                        tiers: [
                            {
                                key: 'standard',
                                max_observations: 100,
                                covered_count: 100,
                                llm_calls: 1,
                                estimated_credits: 1,
                            },
                            {
                                key: 'deep',
                                max_observations: 500,
                                covered_count: 500,
                                llm_calls: 6,
                                estimated_credits: 5,
                            },
                            {
                                key: 'complete',
                                max_observations: 2000,
                                covered_count: 623,
                                llm_calls: 8,
                                estimated_credits: 6,
                            },
                        ],
                    },
                ],
            },
            post: {
                '/api/projects/:team/vision/actions/:action/run/': async ({ request }: { request: Request }) => {
                    runBody = await request.json()
                    return [202, { workflow_id: 'wf-1', already_running: false }]
                },
            },
        })
        await expectLogic(logic, () => {
            logic.actions.openPeriodModal()
        })
            .toDispatchActions(['loadRunPreview', 'loadRunPreviewSuccess'])
            .toFinishAllListeners()
        expect(logic.values.runPreview?.observation_count).toEqual(623)
        // Opening resets to the cheapest tier so an expensive choice never carries over silently.
        expect(logic.values.coverageTier).toEqual('standard')

        await expectLogic(logic, () => {
            logic.actions.setCoverageTier('deep')
            logic.actions.summarizePeriod()
        })
            .toDispatchActions(['summarizePeriodDone'])
            .toFinishAllListeners()
        expect(runBody.max_observations).toEqual(500)
    })

    it('falls back to the mirrored tier caps when the preview fails', async () => {
        // A preview outage must not block generating, and the submitted cap must still match the
        // tier label rather than going out undefined.
        useMocks(mocksFor([DIGEST]))
        mountLogic()
        await expectLogic(logic).toFinishAllListeners()
        let runBody: any = null
        useMocks({
            get: {
                '/api/projects/:team/vision/actions/:action/run_preview/': () => [500, {}],
            },
            post: {
                '/api/projects/:team/vision/actions/:action/run/': async ({ request }: { request: Request }) => {
                    runBody = await request.json()
                    return [202, { workflow_id: 'wf-1', already_running: false }]
                },
            },
        })
        await expectLogic(logic, () => {
            logic.actions.openPeriodModal()
        })
            .toDispatchActions(['loadRunPreviewFailure'])
            .toFinishAllListeners()
        await expectLogic(logic, () => {
            logic.actions.setCoverageTier('complete')
            logic.actions.summarizePeriod()
        })
            .toDispatchActions(['summarizePeriodDone'])
            .toFinishAllListeners()
        expect(runBody.max_observations).toEqual(2000)
        expect(logic.values.runPreviewLoading).toEqual(false)
    })

    it('summarizePeriod keeps the modal open when the server coalesced onto a running digest', async () => {
        // The requested period did not start in that case; closing the modal would misread as success.
        useMocks(mocksFor([DIGEST]))
        mountLogic()
        await expectLogic(logic).toFinishAllListeners()
        useMocks({
            post: {
                '/api/projects/:team/vision/actions/:action/run/': () => [
                    202,
                    { workflow_id: 'wf-1', already_running: true },
                ],
            },
        })
        await expectLogic(logic, () => {
            logic.actions.openPeriodModal()
            logic.actions.summarizePeriod()
        })
            .toDispatchActions(['summarizePeriodDone'])
            .toFinishAllListeners()
        expect(logic.values.periodModalOpen).toBe(true)
        expect(logic.values.summarizingPeriod).toBe(false)
    })
})
