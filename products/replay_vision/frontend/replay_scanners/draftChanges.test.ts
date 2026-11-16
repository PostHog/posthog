import { scannerModelChoice } from './draftChanges'
import type { ScannerFormValues } from './types'

const draftWith = (model: string): ScannerFormValues => ({ model }) as ScannerFormValues

describe('scannerModelChoice', () => {
    it.each([
        ['gemini-3-flash-preview', false, 'unchanged'],
        ['gemini-3.8-flash', true, 'upgrade'],
        ['gemini-3.5-flash-lite', true, 'downgrade'],
    ])('compares a hand-built scanner saved on %s against the default model', (model, changed, direction) => {
        expect(scannerModelChoice('scratch', null, model)).toEqual({
            initial_model_source: 'default',
            initial_model: 'gemini-3-flash-preview',
            model,
            model_changed: changed,
            model_change_direction: direction,
        })
    })

    it('compares against the model the AI draft chose', () => {
        expect(scannerModelChoice('ai', draftWith('gemini-3.8-flash'), 'gemini-3-flash-preview')).toMatchObject({
            initial_model_source: 'ai_draft',
            initial_model: 'gemini-3.8-flash',
            model_changed: true,
            model_change_direction: 'downgrade',
        })
    })

    it('reports an AI draft without a baseline as unknown rather than as unchanged', () => {
        expect(scannerModelChoice('ai', null, 'gemini-3.8-flash')).toMatchObject({
            initial_model_source: 'unknown',
            model_changed: null,
            model_change_direction: null,
        })
    })

    it('leaves the direction unknown for a model with no price', () => {
        expect(scannerModelChoice('ai', draftWith('gemini-3.7-flash'), 'gemini-3.8-flash')).toMatchObject({
            model_changed: true,
            model_change_direction: null,
        })
    })
})
