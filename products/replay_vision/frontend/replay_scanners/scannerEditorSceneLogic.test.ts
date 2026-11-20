import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import {
    advancesWithoutSubmit,
    firstErroredScannerStep,
    isScannerEditorPath,
    nextScannerEditorStep,
    scannerEditorSceneLogic,
    SCANNER_EDITOR_STEPS,
    scannerEditorStepOrder,
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

describe('step order', () => {
    it('asks which recordings to watch before what to look for in them', () => {
        expect(SCANNER_EDITOR_STEPS).toEqual(['goal', 'details', 'triggers', 'configure', 'budget'])
    })

    it('keeps the overview between goal and details', () => {
        const order = scannerEditorStepOrder()
        expect(order.goal).toBeLessThan(order.overview)
        expect(order.overview).toBeLessThan(order.details)
    })

    it('derives the step order from the step list', () => {
        const order = scannerEditorStepOrder()
        expect(order.triggers).toBeLessThan(order.configure)
        expect(order.configure).toBeLessThan(order.budget)
    })

    it('ends the stepper on budget and leaves the overview outside it', () => {
        expect(nextScannerEditorStep('triggers', SCANNER_EDITOR_STEPS)).toBe('configure')
        expect(nextScannerEditorStep('budget', SCANNER_EDITOR_STEPS)).toBeNull()
        expect(nextScannerEditorStep('overview', SCANNER_EDITOR_STEPS)).toBeNull()
    })

    it('labels every step', () => {
        const labels = Object.fromEntries(scannerStepperSteps().map(({ step, label }) => [step, label]))
        expect(labels).toEqual({
            goal: 'Goal',
            details: 'Details',
            triggers: 'Target recordings',
            configure: 'Prompt & output',
            budget: 'Sampling & limits',
        })
    })

    it('keeps the pinned autocapture data-attrs, which dashboards read', () => {
        expect(scannerStepperSteps().map(({ dataAttr }) => dataAttr)).toEqual([
            'vision-editor-step-template',
            'vision-editor-step-details',
            'vision-editor-step-triggers',
            'vision-editor-step-configure',
            'vision-editor-step-budget',
        ])
    })

    it('routes a failed submit to the earliest errored step in that order', () => {
        const errors = { ...PROMPT_ERROR, ...DURATION_ERROR }
        expect(firstErroredScannerStep(errors, SCANNER_EDITOR_STEPS)).toBe('triggers')
    })
})

describe('advancesWithoutSubmit', () => {
    it.each([
        ['triggers past an unreached prompt', 'triggers', PROMPT_ERROR, true],
        ['triggers with its own duration error', 'triggers', DURATION_ERROR, false],
        ['configure with a prompt error', 'configure', PROMPT_ERROR, false],
        ['configure past a later budget error', 'configure', { sampling_rate: 'Bad' }, true],
        ['budget, the final step', 'budget', {}, false],
        ['overview, outside the stepper', 'overview', {}, false],
    ] as const)('%s → %s', (_label, step, errors, expected) => {
        expect(advancesWithoutSubmit(step, errors)).toBe(expected)
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
            ...SCANNER_EDITOR_STEPS.map((step): [string, boolean] => [scannerStepUrl(step, 'abc'), true]),
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

    describe('step labels', () => {
        it.each([
            [urls.replayVisionScannerTriggers('new'), 'Target recordings'],
            [urls.replayVisionScannerConfigure('new'), 'Prompt & output'],
            [urls.replayVisionScannerBudget('new'), 'Sampling & limits'],
        ])('names the current step in the breadcrumb at %s', async (url, name) => {
            router.actions.push(url)
            await expectLogic(logic).toMatchValues({
                breadcrumbs: expect.arrayContaining([expect.objectContaining({ key: 'new-scanner-step', name })]),
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
                    expect.objectContaining({ key: 'new-scanner-step', name: 'Prompt & output' }),
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
