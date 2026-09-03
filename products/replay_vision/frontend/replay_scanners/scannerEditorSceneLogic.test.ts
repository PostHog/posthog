import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { firstErroredScannerStep, scannerEditorSceneLogic } from './scannerEditorSceneLogic'

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

describe('scannerEditorSceneLogic', () => {
    let logic: ReturnType<typeof scannerEditorSceneLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = scannerEditorSceneLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    describe('URL → state', () => {
        it('reflects the template step for a new scanner', async () => {
            router.actions.push(urls.replayVisionScannerTemplate('new'))
            await expectLogic(logic).toMatchValues({
                scannerId: 'new',
                step: 'template',
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

        it('redirects /:id/template → /:id/details for existing scanners', async () => {
            router.actions.push(urls.replayVisionScannerTemplate('abc-123'))
            await expectLogic(logic).toMatchValues({
                scannerId: 'abc-123',
                step: 'details',
                isNew: false,
            })
            expect(router.values.location.pathname.endsWith(urls.replayVisionScannerDetails('abc-123'))).toBe(true)
        })
    })

    describe('breadcrumbs', () => {
        it('points the back-arrow crumb at the template step past it when creating', async () => {
            // The scene back arrow navigates to the second-to-last crumb, so the crumb before
            // the current step must be the template picker or the wizard cannot go back.
            router.actions.push(urls.replayVisionScannerConfigure('new'))
            await expectLogic(logic).toMatchValues({
                breadcrumbs: [
                    expect.objectContaining({ key: 'replay-vision', name: 'Replay vision' }),
                    expect.objectContaining({
                        key: 'new-scanner',
                        name: 'New scanner',
                        path: urls.replayVisionTemplates(),
                    }),
                    expect.objectContaining({ key: 'new-scanner-step', name: 'Configure' }),
                ],
            })
        })

        it('keeps the template param on the back-arrow crumb, so going back preserves the type lock', async () => {
            router.actions.push(urls.replayVisionScannerConfigure('new'), { template: 'dead_end' })
            await expectLogic(logic).toMatchValues({
                breadcrumbs: expect.arrayContaining([
                    expect.objectContaining({
                        key: 'new-scanner',
                        path: `${urls.replayVisionTemplates()}?template=dead_end`,
                    }),
                ]),
            })
        })

        it('shows no step crumb on the template step, so the back arrow exits to the list', async () => {
            router.actions.push(urls.replayVisionScannerTemplate('new'))
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
