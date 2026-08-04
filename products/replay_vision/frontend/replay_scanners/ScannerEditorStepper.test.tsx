import { render } from '@testing-library/react'

import { SCANNER_EDITOR_STEPS, ScannerEditorStep } from './scannerEditorSceneLogic'
import { ScannerEditorStepper } from './ScannerEditorStepper'

describe('ScannerEditorStepper', () => {
    // The scanner form validates every step at once, so the step blocking the wizard is frequently not the
    // one on screen. A marker that only rendered for the current step would leave a user on scan conditions
    // with no hint that configure is what's holding them up.
    it.each([
        { name: 'marks an errored step the user is not on', current: 'triggers', errored: 'configure' },
        { name: 'marks an errored step the user is on', current: 'configure', errored: 'configure' },
        { name: 'marks nothing when no step has errors', current: 'triggers', errored: null },
    ] as { name: string; current: ScannerEditorStep; errored: ScannerEditorStep | null }[])(
        '$name',
        ({ current, errored }) => {
            const { container } = render(
                <ScannerEditorStepper
                    currentStep={current}
                    steps={SCANNER_EDITOR_STEPS}
                    onStepClick={() => {}}
                    stepErrors={errored ? { [errored]: true } : {}}
                />
            )

            const marker = errored
                ? container.querySelector(`[data-attr="vision-editor-step-${errored}"] .text-warning`)
                : container.querySelector('.text-warning')
            expect(marker).toEqual(errored ? expect.anything() : null)
        }
    )
})
