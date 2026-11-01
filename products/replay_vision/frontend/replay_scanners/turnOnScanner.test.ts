import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { LemonDialog, LemonDialogProps } from 'lib/lemon-ui/LemonDialog'
import { organizationLogic } from 'scenes/organizationLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { turnOnScanner } from './turnOnScanner'

const LOST_ACCESS = [400, { type: 'validation_error', code: 'scanner_creator_lost_access', detail: 'x' }]
const SAVED = [200, { id: 's1', enabled: true }]

describe('turnOnScanner', () => {
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

        expect(await turnOnScanner('1', 's1')).toMatchObject({ enabled: true })
        expect(patches).toEqual([{ enabled: true }])
        expect(dialogTitles).toEqual([])
    })

    it.each([
        ['approved', true, [{ enabled: true }, { enabled: true, take_over_as_creator: true }], true],
        ['declined', false, [{ enabled: true }], false],
    ])('takes the scanner over only once the take-over is %s', async (_name, confirm, expectedPatches, turnedOn) => {
        useScenario({ consented: true, responses: [LOST_ACCESS, SAVED], answers: [confirm] })

        const saved = await turnOnScanner('1', 's1')

        expect(saved !== null).toBe(turnedOn)
        expect(patches).toEqual(expectedPatches)
        expect(dialogTitles).toEqual(['Take over this scanner?'])
    })

    it.each([
        ['declines the prompt', [false], 0, false],
        ['cancels the legal terms', [true, false], 0, false],
        ['approves both', [true, true], 1, true],
    ])('without consent, a person who %s', async (_name, answers, scannerPatches, turnedOn) => {
        useScenario({ consented: false, responses: [SAVED], answers: [...answers] })

        const saved = await turnOnScanner('1', 's1')

        expect(saved !== null).toBe(turnedOn)
        expect(patches).toHaveLength(scannerPatches)
        expect(organizationLogic.values.currentOrganization?.is_ai_data_processing_approved).toBe(turnedOn)
    })
})
