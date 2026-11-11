import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { organizationLogic } from 'scenes/organizationLogic'

import { useMocks } from '~/mocks/jest'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import type { VisionQuotaApi } from '../generated/api.schemas'
import { visionQuotaLogic } from '../logics/visionQuotaLogic'
import { type QuickScannerLogicProps, quickScannerLogic } from './quickScannerLogic'

const LOGIC_PROPS: QuickScannerLogicProps = {
    key: 'test:quick-scanner',
    entryPoint: 'test_surface',
    prefill: {
        name: 'Sessions with an error',
        scanner_type: 'summarizer',
        scanner_config: { prompt: 'Describe what the user saw.', length: 'medium' },
        query: { kind: NodeKind.RecordingsQuery },
        sampling_rate: 1,
    },
}

const QUOTA: VisionQuotaApi = {
    credit_limit: 10000,
    credits_used: 0,
    remaining: 10000,
    exhausted: false,
    projected_monthly_credits: 0,
    scanners_monthly_credits: 0,
    backfills_committed_credits: 0,
    free_monthly_credits: 2500,
    credits_settled: 0,
    credits_reserved: 0,
    period_start: '2026-10-01T00:00:00Z',
    period_end: '2026-11-01T00:00:00Z',
} as VisionQuotaApi

describe('quickScannerLogic', () => {
    let createBodies: Record<string, unknown>[]
    let createResponse: [number, Record<string, unknown>]

    function setConsent(approved: boolean): void {
        organizationLogic.mount()
        organizationLogic.actions.loadCurrentOrganizationSuccess({
            ...MOCK_DEFAULT_ORGANIZATION,
            is_ai_data_processing_approved: approved,
        })
    }

    beforeEach(() => {
        createBodies = []
        createResponse = [201, { id: 'scanner-1' }]
        sessionStorage.clear()
        useMocks({
            get: { '/api/environments/:team/vision/quota/': () => [200, QUOTA] },
            post: {
                '/api/projects/:team/vision/scanners/': async ({ request }: { request: Request }) => {
                    createBodies.push(await request.json())
                    return createResponse
                },
                '/api/projects/:team/vision/scanners/estimate/': () => [200, {}],
            },
        })
        initKeaTests()
    })

    // The spend choice is the only thing the person sets here, and a wrong mapping changes their bill.
    it.each([
        {
            case: 'free credits only',
            act: (logic: ReturnType<typeof quickScannerLogic>) => logic.actions.setCreditCap('free'),
            spend: { free_only: true, credit_limit: null },
        },
        {
            case: 'a monthly cap',
            act: (logic: ReturnType<typeof quickScannerLogic>) => {
                logic.actions.setCreditCap('cap')
                logic.actions.setBudget(1200)
            },
            spend: { free_only: false, credit_limit: 1200 },
        },
    ])('creates the prefilled scanner with $case', async ({ act, spend }) => {
        setConsent(true)
        const logic = quickScannerLogic(LOGIC_PROPS)
        logic.mount()
        act(logic)

        await expectLogic(logic, () => logic.actions.startWatching()).toFinishAllListeners()

        expect(createBodies).toEqual([
            expect.objectContaining({
                ...LOGIC_PROPS.prefill,
                ...spend,
                enabled: true,
                entry_point: 'test_surface',
            }),
        ])
        expect(logic.values.createdScanner).toMatchObject({ id: 'scanner-1' })
    })

    it('keeps free credits only when quota runs out while consent is pending', async () => {
        setConsent(false)
        const logic = quickScannerLogic(LOGIC_PROPS)
        logic.mount()
        await expectLogic(logic, () => logic.actions.setPopoverOpen(true)).toFinishAllListeners()
        logic.actions.setCreditCap('free')
        logic.actions.startWatching()

        // With no free credits left, the live choice falls back to a billable budget.
        visionQuotaLogic.actions.loadQuotaSuccess({ ...QUOTA, credits_used: QUOTA.free_monthly_credits })
        expect(logic.values.spendChoice.mode).toEqual('budget')

        await expectLogic(logic, () => logic.actions.approveConsent()).toFinishAllListeners()

        expect(createBodies).toEqual([expect.objectContaining({ free_only: true, credit_limit: null })])
    })

    it('finishes the creation on the page it returns to after an SSO reauthentication', async () => {
        setConsent(false)
        const askingLogic = quickScannerLogic({ ...LOGIC_PROPS, key: 'tab', resumeScope: 'issue-1' })
        askingLogic.mount()
        askingLogic.actions.setCreditCap('cap')
        askingLogic.actions.setBudget(700)
        askingLogic.actions.startWatching()
        askingLogic.actions.rememberConsentIntent()
        // The reauthentication unloads the page before the approval resolves.
        askingLogic.unmount()

        setConsent(true)
        const returnedLogic = quickScannerLogic({
            ...LOGIC_PROPS,
            key: 'header',
            entryPoint: 'other_surface',
            resumeScope: 'issue-1',
        })
        await expectLogic(returnedLogic, () => {
            returnedLogic.mount()
        }).toFinishAllListeners()

        expect(createBodies).toEqual([
            expect.objectContaining({ free_only: false, credit_limit: 700, entry_point: 'test_surface' }),
        ])
        expect(returnedLogic.values.popoverOpen).toBe(true)
    })

    it.each([
        {
            case: 'a server error',
            response: [500, { detail: 'nope' }],
            message: "Couldn't create the scanner. Try again.",
        },
        {
            case: 'a scanner that already exists',
            response: [
                400,
                { type: 'validation_error', attr: 'name', detail: 'A scanner with this name already exists.' },
            ],
            message: 'Replay vision already watches this. Find its scanner in Replay vision.',
        },
    ])('explains $case and creates nothing', async ({ response, message }) => {
        createResponse = response as [number, Record<string, unknown>]
        setConsent(true)
        const logic = quickScannerLogic(LOGIC_PROPS)
        logic.mount()

        await expectLogic(logic, () => logic.actions.startWatching()).toFinishAllListeners()

        expect(logic.values.createError).toEqual(message)
        expect(logic.values.createdScanner).toBeNull()
    })
})
