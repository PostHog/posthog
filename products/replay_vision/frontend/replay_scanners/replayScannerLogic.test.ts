import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { replayScannerLogic } from './replayScannerLogic'
import { ClassifierScanner, ScorerScanner } from './types'

describe('replayScannerLogic', () => {
    let logic: ReturnType<typeof replayScannerLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team/vision/scanners/:id/': () => [404, {}],
                '/api/environments/:team/vision/scanners/:id/observations/': { results: [] },
            },
        })
        initKeaTests()
        logic = replayScannerLogic({ id: 'new', tabId: 'test' })
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    describe('form defaults', () => {
        it('new scanner starts as monitor with empty prompt and default sampling', () => {
            expect(logic.values.scanner).toMatchObject({
                id: 'new',
                name: '',
                enabled: true,
                scanner_type: 'monitor',
                scanner_config: { prompt: '' },
                sampling_rate: 1,
            })
        })
    })

    describe('setScannerType', () => {
        it.each([
            { type: 'monitor' as const, expectedConfig: { prompt: '' } },
            { type: 'summarizer' as const, expectedConfig: { prompt: '', length: 'medium' } },
            { type: 'classifier' as const, expectedConfig: { prompt: '', tags: [], multi_label: true } },
            { type: 'scorer' as const, expectedConfig: { prompt: '', scale: { min: 0, max: 10 } } },
            { type: 'indexer' as const, expectedConfig: { prompt: '' } },
        ])(
            'switching to $type replaces scanner_config with the default for that type',
            async ({ type, expectedConfig }) => {
                await expectLogic(logic, () => logic.actions.setScannerType(type)).toMatchValues({
                    scanner: expect.objectContaining({ scanner_type: type, scanner_config: expectedConfig }),
                })
            }
        )

        it('does not preserve old prompt across type changes', async () => {
            logic.actions.setScannerValues({ scanner_config: { prompt: 'Was there a refund?' } })
            await expectLogic(logic, () => logic.actions.setScannerType('summarizer')).toMatchValues({
                scanner: expect.objectContaining({ scanner_config: { prompt: '', length: 'medium' } }),
            })
        })
    })

    describe('validation errors', () => {
        it.each([
            {
                name: 'flags missing name',
                setup: () => undefined,
                expectedErrors: { name: 'Name is required' },
            },
            {
                name: 'flags missing prompt',
                setup: () => undefined,
                expectedErrors: { scanner_config: expect.objectContaining({ prompt: 'Prompt is required' }) },
            },
            {
                name: 'flags sampling rate outside (0, 1]',
                setup: () => logic.actions.setScannerValues({ sampling_rate: 0 }),
                expectedErrors: { sampling_rate: expect.any(String) },
            },
            {
                name: 'flags scorer scale when min >= max',
                setup: () => {
                    logic.actions.setScannerType('scorer')
                    logic.actions.setScannerValues({
                        scanner_config: {
                            prompt: 'rate this',
                            scale: { min: 10, max: 5 },
                        } as ScorerScanner['scanner_config'],
                    })
                },
                expectedErrors: {
                    scanner_config: expect.objectContaining({ scale: expect.stringContaining('greater than') }),
                },
            },
        ])('$name', async ({ setup, expectedErrors }) => {
            setup()
            await expectLogic(logic).toMatchValues({
                scannerValidationErrors: expect.objectContaining(expectedErrors),
            })
        })

        it('passes when all required fields are filled', async () => {
            logic.actions.setScannerType('classifier')
            logic.actions.setScannerValues({
                name: 'My scanner',
                sampling_rate: 0.1,
                scanner_config: {
                    prompt: 'Categorize',
                    tags: ['a'],
                    multi_label: true,
                } as ClassifierScanner['scanner_config'],
            })
            await expectLogic(logic).toMatchValues({
                isScannerValid: true,
            })
        })
    })

    describe('hasUnsavedChanges', () => {
        it('is false when no original scanner is loaded', () => {
            expect(logic.values.hasUnsavedChanges).toBe(false)
        })

        it('is false when current matches original', async () => {
            logic.actions.loadScannerSuccess({
                ...logic.values.scanner!,
                id: 'abc',
                name: 'Loaded',
            })
            await expectLogic(logic).toMatchValues({ hasUnsavedChanges: false })
        })

        it('is true after a form edit', async () => {
            logic.actions.loadScannerSuccess({
                ...logic.values.scanner!,
                id: 'abc',
                name: 'Loaded',
            })
            await expectLogic(logic, () => logic.actions.setScannerValues({ name: 'Edited' })).toMatchValues({
                hasUnsavedChanges: true,
            })
        })
    })
})
