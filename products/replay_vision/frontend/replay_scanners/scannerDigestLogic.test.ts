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
    trigger_config: { rrule: 'FREQ=DAILY;BYHOUR=8;BYMINUTE=0', timezone: 'UTC' },
    delivery_config: [],
} as unknown as VisionActionApi

const OTHER_SUMMARY = {
    id: 'a1',
    name: 'slack summary',
    scanner: 's1',
    enabled: true,
    is_scanner_digest: false,
    trigger_config: { rrule: 'FREQ=DAILY' },
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

    it('one-click create sends the digest marker and defaults, then reloads the list', async () => {
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
        await expectLogic(logic, () => {
            logic.actions.createDigest()
        })
            .toDispatchActions(['createDigestSuccess', 'loadActions'])
            .toFinishAllListeners()
        expect(body).toMatchObject({
            name: 'Daily digest: my-scanner',
            scanner: 's1',
            is_scanner_digest: true,
            trigger_config: { rrule: 'FREQ=DAILY;BYHOUR=8;BYMINUTE=0' },
            delivery_config: [],
        })
    })
})
