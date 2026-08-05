import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { scannerEditorSceneLogic } from './scannerEditorSceneLogic'

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

        it('redirects /:id/template → /:id/configure for existing scanners', async () => {
            router.actions.push(urls.replayVisionScannerTemplate('abc-123'))
            await expectLogic(logic).toMatchValues({
                scannerId: 'abc-123',
                step: 'configure',
                isNew: false,
            })
            expect(router.values.location.pathname.endsWith(urls.replayVisionScannerConfigure('abc-123'))).toBe(true)
        })
    })

    describe('visibleSteps', () => {
        it('shows all four steps for a new scanner', async () => {
            router.actions.push(urls.replayVisionScannerConfigure('new'))
            await expectLogic(logic).toMatchValues({
                visibleSteps: ['template', 'configure', 'triggers', 'self_driving'],
            })
        })

        it('hides only the template step for an existing scanner', async () => {
            router.actions.push(urls.replayVisionScannerConfigure('abc-123'))
            await expectLogic(logic).toMatchValues({
                visibleSteps: ['configure', 'triggers', 'self_driving'],
            })
        })
    })

    describe('breadcrumbs', () => {
        it('labels the new-scanner trail when creating', async () => {
            router.actions.push(urls.replayVisionScannerConfigure('new'))
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
