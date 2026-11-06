import { isTextEntryTarget, resolveReportCardClickIntent } from './reportSelection'

describe('resolveReportCardClickIntent', () => {
    const plain = { shiftKey: false, metaKey: false, ctrlKey: false }

    test.each([
        ['plain click with nothing selected opens the report', plain, false, 'open'],
        ['plain click in selection mode toggles instead of opening', plain, true, 'toggle'],
        ['cmd-click opens from an empty selection', { ...plain, metaKey: true }, false, 'open'],
        ['ctrl-click opens from an empty selection', { ...plain, ctrlKey: true }, false, 'open'],
        ['cmd-click opens in selection mode', { ...plain, metaKey: true }, true, 'open'],
        ['ctrl-click opens in selection mode', { ...plain, ctrlKey: true }, true, 'open'],
        ['shift-click ranges', { ...plain, shiftKey: true }, true, 'range'],
        ['cmd wins over shift', { shiftKey: true, metaKey: true, ctrlKey: false }, true, 'open'],
        ['ctrl wins over shift', { shiftKey: true, metaKey: false, ctrlKey: true }, true, 'open'],
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
