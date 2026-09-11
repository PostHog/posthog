import { isTextEntryTarget, resolveReportCardClickIntent } from './reportSelection'

describe('resolveReportCardClickIntent', () => {
    const plain = { shiftKey: false, metaKey: false, ctrlKey: false }

    test.each([
        ['plain click with nothing selected opens the report', plain, false, 'open'],
        ['plain click in selection mode toggles instead of opening', plain, true, 'toggle'],
        ['cmd-click toggles from an empty selection', { ...plain, metaKey: true }, false, 'toggle'],
        ['ctrl-click toggles from an empty selection', { ...plain, ctrlKey: true }, false, 'toggle'],
        ['shift-click ranges', { ...plain, shiftKey: true }, true, 'range'],
        ['shift wins over cmd', { shiftKey: true, metaKey: true, ctrlKey: false }, true, 'range'],
    ])('%s', (_name, modifiers, hasSelection, expected) => {
        expect(resolveReportCardClickIntent(modifiers, hasSelection)).toBe(expected)
    })
})

describe('isTextEntryTarget', () => {
    it('does not treat a checkbox as text entry', () => {
        const checkbox = document.createElement('input')
        checkbox.type = 'checkbox'

        expect(isTextEntryTarget(checkbox)).toBe(false)
    })

    it('treats text inputs and text areas as text entry', () => {
        expect(isTextEntryTarget(document.createElement('input'))).toBe(true)
        expect(isTextEntryTarget(document.createElement('textarea'))).toBe(true)
    })
})
