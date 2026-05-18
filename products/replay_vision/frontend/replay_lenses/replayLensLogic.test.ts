import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { replayLensLogic } from './replayLensLogic'
import { ClassifierLens, ScorerLens } from './types'

describe('replayLensLogic', () => {
    let logic: ReturnType<typeof replayLensLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team/vision/lenses/:id/': () => [404, {}],
                '/api/environments/:team/vision/lenses/:id/observations/': { results: [] },
            },
        })
        initKeaTests()
        logic = replayLensLogic({ id: 'new', tabId: 'test' })
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    describe('form defaults', () => {
        it('new lens starts as monitor with empty prompt and default sampling', () => {
            expect(logic.values.lens).toMatchObject({
                id: 'new',
                name: '',
                enabled: true,
                lens_type: 'monitor',
                lens_config: { prompt: '' },
                sampling_rate: 1,
            })
        })
    })

    describe('setLensType', () => {
        it.each([
            { type: 'monitor' as const, expectedConfig: { prompt: '' } },
            { type: 'summarizer' as const, expectedConfig: { prompt: '', length: 'medium' } },
            { type: 'classifier' as const, expectedConfig: { prompt: '', tags: [], multi_label: true } },
            { type: 'scorer' as const, expectedConfig: { prompt: '', scale: { min: 0, max: 10 } } },
            { type: 'indexer' as const, expectedConfig: { prompt: '' } },
        ])(
            'switching to $type replaces lens_config with the default for that type',
            async ({ type, expectedConfig }) => {
                await expectLogic(logic, () => logic.actions.setLensType(type)).toMatchValues({
                    lens: expect.objectContaining({ lens_type: type, lens_config: expectedConfig }),
                })
            }
        )

        it('does not preserve old prompt across type changes', async () => {
            logic.actions.setLensValues({ lens_config: { prompt: 'Was there a refund?' } })
            await expectLogic(logic, () => logic.actions.setLensType('summarizer')).toMatchValues({
                lens: expect.objectContaining({ lens_config: { prompt: '', length: 'medium' } }),
            })
        })
    })

    describe('validation errors', () => {
        it('flags missing name', () => {
            expect(logic.values.lensValidationErrors).toMatchObject({ name: 'Name is required' })
        })

        it('flags missing prompt', () => {
            expect(logic.values.lensValidationErrors).toMatchObject({
                lens_config: expect.objectContaining({ prompt: 'Prompt is required' }),
            })
        })

        it('flags sampling rate outside (0, 1]', async () => {
            logic.actions.setLensValues({ sampling_rate: 0 })
            await expectLogic(logic).toMatchValues({
                lensValidationErrors: expect.objectContaining({
                    sampling_rate: expect.any(String),
                }),
            })
        })

        it('flags scorer scale when min >= max', async () => {
            logic.actions.setLensType('scorer')
            logic.actions.setLensValues({
                lens_config: { prompt: 'rate this', scale: { min: 10, max: 5 } } as ScorerLens['lens_config'],
            })
            await expectLogic(logic).toMatchValues({
                lensValidationErrors: expect.objectContaining({
                    lens_config: expect.objectContaining({ scale: expect.stringContaining('greater than') }),
                }),
            })
        })

        it('passes when all required fields are filled', async () => {
            logic.actions.setLensType('classifier')
            logic.actions.setLensValues({
                name: 'My lens',
                sampling_rate: 0.1,
                lens_config: { prompt: 'Categorize', tags: ['a'], multi_label: true } as ClassifierLens['lens_config'],
            })
            await expectLogic(logic).toMatchValues({
                isLensValid: true,
            })
        })
    })

    describe('hasUnsavedChanges', () => {
        it('is false when no original lens is loaded', () => {
            expect(logic.values.hasUnsavedChanges).toBe(false)
        })

        it('is false when current matches original', async () => {
            logic.actions.loadLensSuccess({
                ...logic.values.lens!,
                id: 'abc',
                name: 'Loaded',
            })
            await expectLogic(logic).toMatchValues({ hasUnsavedChanges: false })
        })

        it('is true after a form edit', async () => {
            logic.actions.loadLensSuccess({
                ...logic.values.lens!,
                id: 'abc',
                name: 'Loaded',
            })
            await expectLogic(logic, () => logic.actions.setLensValues({ name: 'Edited' })).toMatchValues({
                hasUnsavedChanges: true,
            })
        })
    })
})
