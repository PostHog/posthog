import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

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

describe('quickScannerLogic', () => {
    let createBodies: Record<string, unknown>[]
    let createStatus: number

    beforeEach(() => {
        createBodies = []
        createStatus = 201
        useMocks({
            post: {
                '/api/projects/:team/vision/scanners/': async ({ request }: { request: Request }) => {
                    createBodies.push(await request.json())
                    return createStatus === 201 ? [201, { id: 'scanner-1' }] : [createStatus, { detail: 'nope' }]
                },
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
        const logic = quickScannerLogic(LOGIC_PROPS)
        logic.mount()
        act(logic)

        await expectLogic(logic, () => logic.actions.createScanner()).toFinishAllListeners()

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

    it('shows the failure and creates nothing when the request fails', async () => {
        createStatus = 500
        const logic = quickScannerLogic(LOGIC_PROPS)
        logic.mount()

        await expectLogic(logic, () => logic.actions.createScanner()).toFinishAllListeners()

        expect(logic.values.createError).toBe(true)
        expect(logic.values.createdScanner).toBeNull()
    })
})
