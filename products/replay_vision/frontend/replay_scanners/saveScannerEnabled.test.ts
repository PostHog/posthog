import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { LemonDialog, LemonDialogProps } from 'lib/lemon-ui/LemonDialog'
import { organizationLogic } from 'scenes/organizationLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { saveScannerEnabled } from './saveScannerEnabled'

const LOST_ACCESS = [400, { type: 'validation_error', code: 'scanner_creator_lost_access', detail: 'x' }]
const FREE_CREDITS_USED = [400, { type: 'validation_error', code: 'scanner_free_credits_used', detail: 'x' }]
const SAVED = [200, { id: 's1', enabled: true }]

describe('saveScannerEnabled', () => {
    let patches: Record<string, unknown>[]
    let dialogTitles: string[]

    function useScenario({
        consented,
        responses,
        answers,
    }: {
        consented: boolean
        responses: unknown[][]
        answers: boolean[]
    }): void {
        patches = []
        dialogTitles = []
        useMocks({
            patch: {
                '/api/projects/:team/vision/scanners/:id/': async ({ request }: { request: Request }) => {
                    patches.push(await request.json())
                    return responses[patches.length - 1] as any
                },
                '/api/organizations/:id/': () => [
                    200,
                    { ...MOCK_DEFAULT_ORGANIZATION, is_ai_data_processing_approved: true },
                ],
            },
        })
        organizationLogic.mount()
        organizationLogic.actions.loadCurrentOrganizationSuccess({
            ...MOCK_DEFAULT_ORGANIZATION,
            is_ai_data_processing_approved: consented,
        })
        // Each dialog takes the next answer: confirm runs the primary button, then the dialog closes.
        jest.spyOn(LemonDialog, 'open').mockImplementation(async (props: LemonDialogProps) => {
            dialogTitles.push(String(props.title))
            if (answers.shift()) {
                await (props.primaryButton?.onClick as (() => unknown) | undefined)?.()
            }
            props.onAfterClose?.()
        })
    }

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('turns on without asking when nothing is in the way', async () => {
        useScenario({ consented: true, responses: [SAVED], answers: [] })

        expect(await saveScannerEnabled('1', 's1', true)).toMatchObject({ enabled: true })
        expect(patches).toEqual([{ enabled: true }])
        expect(dialogTitles).toEqual([])
    })

    it.each([
        [
            'takes the scanner over once approved',
            LOST_ACCESS,
            true,
            [{ enabled: true }, { enabled: true, take_over_as_creator: true }],
            true,
            'Take over this scanner?',
        ],
        [
            'keeps it off when the take-over is declined',
            LOST_ACCESS,
            false,
            [{ enabled: true }],
            false,
            'Take over this scanner?',
        ],
        [
            'turns off free credits only once approved',
            FREE_CREDITS_USED,
            true,
            [{ enabled: true }, { enabled: true, free_only: false }],
            true,
            'Turn off free credits only and start scanning?',
        ],
        [
            'keeps it free-only and off when declined',
            FREE_CREDITS_USED,
            false,
            [{ enabled: true }],
            false,
            'Turn off free credits only and start scanning?',
        ],
    ])('%s', async (_name, refusal, confirm, expectedPatches, turnedOn, dialogTitle) => {
        useScenario({ consented: true, responses: [refusal, SAVED], answers: [confirm] })

        const saved = await saveScannerEnabled('1', 's1', true)

        expect(saved !== null).toBe(turnedOn)
        expect(patches).toEqual(expectedPatches)
        expect(dialogTitles).toEqual([dialogTitle])
    })

    it.each([
        ['declines the prompt', [false], 0, false],
        ['cancels the legal terms', [true, false], 0, false],
        ['approves both', [true, true], 1, true],
    ])('without consent, a person who %s', async (_name, answers, scannerPatches, turnedOn) => {
        useScenario({ consented: false, responses: [SAVED], answers: [...answers] })

        const saved = await saveScannerEnabled('1', 's1', true)

        expect(saved !== null).toBe(turnedOn)
        expect(patches).toHaveLength(scannerPatches)
        expect(organizationLogic.values.currentOrganization?.is_ai_data_processing_approved).toBe(turnedOn)
    })
})
