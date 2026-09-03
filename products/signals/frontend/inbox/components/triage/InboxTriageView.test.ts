import { TriageEnterIntent, triageEnterIntent } from './InboxTriageView'

describe('triageEnterIntent', () => {
    const button = (): HTMLElement => document.createElement('button')
    const link = (): HTMLElement => document.createElement('a')
    const plain = (): HTMLElement => document.createElement('div')
    const buttonInDialog = (): HTMLElement => {
        const dialog = document.createElement('div')
        dialog.className = 'LemonModal'
        const child = document.createElement('button')
        dialog.append(child)
        return child
    }

    it.each<[string, () => HTMLElement | null, boolean, TriageEnterIntent]>([
        // The regression this guards: Command/Ctrl+Enter must open the report even when a
        // just-clicked control (e.g. the "Read summary" toggle) still holds focus.
        ['a focused button with a modifier opens the report', button, true, 'open'],
        // Plain Enter on a focused button still activates the button, not the card toggle.
        ['a focused button without a modifier is passed through', button, false, 'passthrough'],
        // A focused link keeps its own Enter (activate it, or open in a new tab with the modifier).
        ['a focused link with a modifier is passed through', link, true, 'passthrough'],
        ['a focused link without a modifier is passed through', link, false, 'passthrough'],
        // A key inside a dialog belongs to the dialog, even with a modifier held.
        ['a control inside a dialog is passed through', buttonInDialog, true, 'passthrough'],
        // Away from any control, the modifier opens the report and plain Enter toggles the card.
        ['a modifier away from any control opens the report', plain, true, 'open'],
        ['plain Enter away from any control toggles the card', plain, false, 'toggle'],
        ['no focused element still toggles on plain Enter', () => null, false, 'toggle'],
    ])('%s', (_name, makeTarget, hasModifier, expected) => {
        expect(triageEnterIntent(makeTarget(), hasModifier)).toBe(expected)
    })
})
