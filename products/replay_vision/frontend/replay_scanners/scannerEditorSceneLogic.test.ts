import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import {
    advancesWithoutSubmit,
    firstErroredScannerStep,
    isScannerEditorPath,
    nextScannerEditorStep,
    scannerEditorSceneLogic,
    scannerEditorStepOrder,
    scannerEditorSteps,
    scannerStepErrors,
    scannerStepperSteps,
    scannerStepUrl,
} from './scannerEditorSceneLogic'

const PROMPT_ERROR = { scanner_config: { prompt: 'Prompt is required' } }
const DURATION_ERROR = { duration: 'Duration filters above 1 hour match nothing' }

describe('firstErroredScannerStep', () => {
    it.each([
        ['config error lands on configure', { scanner_config: { prompt: 'Required' } }, 'configure'],
        ['sampling error lands on budget', { sampling_rate: 'Out of range' }, 'budget'],
        ['credit limit error lands on budget', { credit_limit: 'Enter a credit amount' }, 'budget'],
        ['no errors maps nowhere', {}, null],
    ])('%s', (_label, errors, expected) => {
        expect(firstErroredScannerStep(errors)).toBe(expected)
    })
})

describe('step order by experiment arm', () => {
    it('asks for the prompt before the recordings in control, and after them in recordings-first', () => {
        expect(scannerEditorSteps(false)).toEqual(['goal', 'details', 'configure', 'triggers', 'budget'])
        expect(scannerEditorSteps(true)).toEqual(['goal', 'details', 'triggers', 'configure', 'budget'])
    })

    it.each([false, true])('keeps the overview between goal and details (recordingsFirst=%s)', (recordingsFirst) => {
        const order = scannerEditorStepOrder(recordingsFirst)
        expect(order.goal).toBeLessThan(order.overview)
        expect(order.overview).toBeLessThan(order.details)
    })

    it('derives the recordings-first order from its step list', () => {
        const order = scannerEditorStepOrder(true)
        expect(order.triggers).toBeLessThan(order.configure)
        expect(order.configure).toBeLessThan(order.budget)
    })

    it('ends the stepper on budget and leaves the overview outside it', () => {
        expect(nextScannerEditorStep('triggers', scannerEditorSteps(true))).toBe('configure')
        expect(nextScannerEditorStep('budget', scannerEditorSteps(true))).toBeNull()
        expect(nextScannerEditorStep('overview', scannerEditorSteps(true))).toBeNull()
    })

    it('renames the steps in recordings-first but keeps their autocapture data-attrs', () => {
        const labels = (recordingsFirst: boolean): Record<string, string> =>
            Object.fromEntries(scannerStepperSteps(recordingsFirst).map(({ step, label }) => [step, label]))
        const dataAttrs = (recordingsFirst: boolean): Record<string, string | undefined> =>
            Object.fromEntries(scannerStepperSteps(recordingsFirst).map(({ step, dataAttr }) => [step, dataAttr]))
        expect(labels(true)).toEqual({
            goal: 'Goal',
            details: 'Details',
            triggers: 'Target recordings',
            configure: 'Prompt & output',
            budget: 'Sampling & limits',
        })
        expect(dataAttrs(true)).toEqual(dataAttrs(false))
    })

    it('routes a failed submit to the earliest errored step in the arm’s order', () => {
        const errors = { ...PROMPT_ERROR, ...DURATION_ERROR }
        expect(firstErroredScannerStep(errors, scannerEditorSteps(false))).toBe('configure')
        expect(firstErroredScannerStep(errors, scannerEditorSteps(true))).toBe('triggers')
    })
})

describe('advancesWithoutSubmit', () => {
    it.each([
        ['control goal', 'goal', false, PROMPT_ERROR, true],
        ['control details', 'details', false, PROMPT_ERROR, true],
        ['control configure even when clean', 'configure', false, {}, false],
        ['control triggers with a prompt error', 'triggers', false, PROMPT_ERROR, false],
        ['recordings-first triggers past an unreached prompt', 'triggers', true, PROMPT_ERROR, true],
        ['recordings-first triggers with its own duration error', 'triggers', true, DURATION_ERROR, false],
        ['recordings-first configure with a prompt error', 'configure', true, PROMPT_ERROR, false],
        ['recordings-first configure past a later budget error', 'configure', true, { sampling_rate: 'Bad' }, true],
        ['recordings-first budget, the final step', 'budget', true, {}, false],
        ['recordings-first overview, outside the stepper', 'overview', true, {}, false],
    ] as const)('%s → %s', (_label, step, recordingsFirst, errors, expected) => {
        expect(advancesWithoutSubmit(step, recordingsFirst, errors)).toBe(expected)
    })
})

describe('scannerStepErrors', () => {
    it('carries the field-level messages through to each step', () => {
        expect(
            scannerStepErrors({
                scanner_config: { prompt: 'Prompt is required' },
                sampling_rate: 'Sampling rate must be between 0% and 100%',
                duration: 'Duration filters above 1 hour match nothing',
            })
        ).toEqual({
            goal: [],
            overview: [],
            details: [],
            configure: ['Prompt is required'],
            triggers: ['Duration filters above 1 hour match nothing'],
            budget: ['Sampling rate must be between 0% and 100%'],
        })
    })
})

describe('scannerEditorSceneLogic', () => {
    let logic: ReturnType<typeof scannerEditorSceneLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = scannerEditorSceneLogic()
        logic.mount()
    })

    afterEach(() => {
        jest.restoreAllMocks()
        logic?.unmount()
    })

    describe('isScannerEditorPath', () => {
        it.each<[string, boolean]>([
            ...scannerEditorSteps(false).map((step): [string, boolean] => [scannerStepUrl(step, 'abc'), true]),
            [scannerStepUrl('overview', 'new'), true],
            [`/project/123${urls.replayVisionScannerBudget('abc')}`, true],
            [urls.replayVision('abc'), false],
            [urls.replayVisionObservation('abc'), false],
            [urls.replayVision(), false],
        ])('%s → %s', (pathname, expected) => {
            expect(isScannerEditorPath(pathname)).toBe(expected)
        })
    })

    describe('leaveEditor', () => {
        it('pushes the destination when the unwind lands on a fresh tab’s first entry', () => {
            // A fresh tab's first entry has no history state, so the first push gets count 1.
            let count = 0
            jest.spyOn(window.history, 'state', 'get').mockImplementation(() => (count ? { count } : null))
            jest.spyOn(window.history, 'go').mockImplementation((delta = 0) => {
                count += delta
                window.dispatchEvent(new PopStateEvent('popstate'))
            })
            count = 1
            router.actions.push(urls.replayVisionScannerGoal('new'))
            count = 2
            router.actions.push(urls.replayVisionScannerConfigure('new'))
            const push = jest.spyOn(router.actions, 'push')

            logic.actions.leaveEditor(urls.replayVision('created'))

            expect(push).toHaveBeenCalledWith(urls.replayVision('created'))
        })
    })

    describe('recordings-first experiment', () => {
        afterEach(() => {
            // Flags persist across kea resets, so the variant would leak into later tests.
            featureFlagLogic.actions.setFeatureFlags([], {})
        })

        it.each([
            ['test', urls.replayVisionScannerTriggers('new'), true],
            ['control', urls.replayVisionScannerTriggers('new'), false],
            // Editing an existing scanner stays on the control order, so only creation is exposed.
            ['test', urls.replayVisionScannerTriggers('abc-123'), false],
        ])('variant %s at %s → %s', async (variant, url, expected) => {
            featureFlagLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.VISION_SCANNER_WIZARD_RECORDINGS_FIRST]: variant,
            })
            router.actions.push(url)
            await expectLogic(logic).toMatchValues({
                recordingsFirst: expected,
                steps: scannerEditorSteps(expected),
            })
        })

        it('names the current step with the arm’s label in the breadcrumb', async () => {
            featureFlagLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.VISION_SCANNER_WIZARD_RECORDINGS_FIRST]: 'test',
            })
            router.actions.push(urls.replayVisionScannerTriggers('new'))
            await expectLogic(logic).toMatchValues({
                breadcrumbs: expect.arrayContaining([
                    expect.objectContaining({ key: 'new-scanner-step', name: 'Target recordings' }),
                ]),
            })
        })
    })

    describe('URL → state', () => {
        it('reflects the goal step for a new scanner', async () => {
            router.actions.push(urls.replayVisionScannerGoal('new'))
            await expectLogic(logic).toMatchValues({
                scannerId: 'new',
                step: 'goal',
                isNew: true,
            })
        })

        it('reflects the configure step for a new scanner', async () => {
            router.actions.push(urls.replayVisionScannerConfigure('new'))
            await expectLogic(logic).toMatchValues({
                scannerId: 'new',
                step: 'configure',
                isNew: true,
            })
        })

        it('reflects the triggers step for an existing scanner', async () => {
            router.actions.push(urls.replayVisionScannerTriggers('abc-123'))
            await expectLogic(logic).toMatchValues({
                scannerId: 'abc-123',
                step: 'triggers',
                isNew: false,
            })
        })

        it('redirects /:id/goal → /:id/details for existing scanners', async () => {
            router.actions.push(urls.replayVisionScannerGoal('abc-123'))
            await expectLogic(logic).toMatchValues({
                scannerId: 'abc-123',
                step: 'details',
                isNew: false,
            })
            expect(router.values.location.pathname.endsWith(urls.replayVisionScannerDetails('abc-123'))).toBe(true)
        })
    })

    describe('breadcrumbs', () => {
        it('points the back-arrow crumb at the goal step past it when creating', async () => {
            // The scene back arrow navigates to the second-to-last crumb, so the crumb before
            // the current step must be the goal step or the wizard cannot go back.
            router.actions.push(urls.replayVisionScannerConfigure('new'))
            await expectLogic(logic).toMatchValues({
                breadcrumbs: [
                    expect.objectContaining({ key: 'replay-vision', name: 'Replay vision' }),
                    expect.objectContaining({
                        key: 'new-scanner',
                        name: 'New scanner',
                        path: urls.replayVisionNewScanner(),
                    }),
                    expect.objectContaining({ key: 'new-scanner-step', name: 'Configure' }),
                ],
            })
        })

        it('shows no step crumb on the goal step, so the back arrow exits to the list', async () => {
            router.actions.push(urls.replayVisionScannerGoal('new'))
            await expectLogic(logic).toMatchValues({
                breadcrumbs: [
                    expect.objectContaining({ key: 'replay-vision', name: 'Replay vision' }),
                    expect.objectContaining({ key: 'new-scanner', name: 'New scanner' }),
                ],
            })
        })

        it('labels the scanner trail when editing', async () => {
            router.actions.push(urls.replayVisionScannerConfigure('abc-123'))
            await expectLogic(logic).toMatchValues({
                breadcrumbs: [
                    expect.objectContaining({ key: 'replay-vision', name: 'Replay vision' }),
                    expect.objectContaining({ key: 'scanner-abc-123', name: 'Scanner' }),
                    expect.objectContaining({ key: 'scanner-abc-123-edit', name: 'Edit' }),
                ],
            })
        })
    })
})
