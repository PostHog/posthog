import { cleanup, renderHook } from '@testing-library/react'

import type { SessionConfigOption } from '../conversation/acp-types'
import {
    ComposerShortcutsOptions,
    cycleModeAndCancelGuards,
    handleComposerKeyDown,
    useComposerShortcuts,
} from './composerShortcuts'

const MODE_OPTION: SessionConfigOption = {
    type: 'select',
    id: 'mode',
    name: 'Mode',
    category: 'mode',
    currentValue: 'default',
    options: [
        { value: 'plan', name: 'Plan' },
        { value: 'default', name: 'Default' },
        { value: 'acceptEdits', name: 'Accept edits' },
        { value: 'bypassPermissions', name: 'Bypass' },
    ],
}

const BOOLEAN_OPTION: SessionConfigOption = {
    type: 'boolean',
    id: 'verbose',
    name: 'Verbose',
    currentValue: true,
}

function makeOptions(overrides: Partial<ComposerShortcutsOptions> = {}): ComposerShortcutsOptions {
    return {
        agentBusy: false,
        onCancel: jest.fn(),
        modeOption: MODE_OPTION,
        onModeChange: jest.fn(),
        ...overrides,
    }
}

function keydown(init: KeyboardEventInit): KeyboardEvent {
    return new KeyboardEvent('keydown', { bubbles: true, cancelable: true, ...init })
}

describe('composerShortcuts', () => {
    afterEach(() => {
        cleanup()
        document.body.innerHTML = ''
    })

    describe('cycleModeAndCancelGuards.shouldCycleModeOnShiftTab', () => {
        it.each([
            ['textarea not focused', false, MODE_OPTION, false, undefined],
            ['disabled', true, MODE_OPTION, true, undefined],
            ['no mode option', true, undefined, false, undefined],
            ['non-select mode option', true, BOOLEAN_OPTION, false, undefined],
            ['all guards pass', true, MODE_OPTION, false, 'acceptEdits'],
        ] as [string, boolean, SessionConfigOption | undefined, boolean, string | undefined][])(
            'returns %p result when %s',
            (_label, targetIsTextarea, modeOption, disabled, expected) => {
                expect(
                    cycleModeAndCancelGuards.shouldCycleModeOnShiftTab(targetIsTextarea, modeOption, disabled, false)
                ).toBe(expected)
            }
        )

        it('skips bypass modes by default, wrapping back to the first option', () => {
            const fromAcceptEdits = { ...MODE_OPTION, currentValue: 'acceptEdits' }
            expect(cycleModeAndCancelGuards.shouldCycleModeOnShiftTab(true, fromAcceptEdits, false, false)).toBe('plan')
        })

        it('includes bypass modes when explicitly allowed', () => {
            const fromAcceptEdits = { ...MODE_OPTION, currentValue: 'acceptEdits' }
            expect(cycleModeAndCancelGuards.shouldCycleModeOnShiftTab(true, fromAcceptEdits, false, true)).toBe(
                'bypassPermissions'
            )
        })

        it('falls back to the first option when the current value is unknown', () => {
            const unknownCurrent = { ...MODE_OPTION, currentValue: 'mystery' }
            expect(cycleModeAndCancelGuards.shouldCycleModeOnShiftTab(true, unknownCurrent, false, false)).toBe('plan')
        })

        it('returns undefined when the select has no options', () => {
            const empty = { ...MODE_OPTION, options: [] }
            expect(cycleModeAndCancelGuards.shouldCycleModeOnShiftTab(true, empty, false, false)).toBeUndefined()
        })
    })

    describe('cycleModeAndCancelGuards.shouldCancelOnEscape', () => {
        it.each([
            [true, true],
            [false, false],
        ])('returns %p when agentBusy is %p', (agentBusy, expected) => {
            expect(cycleModeAndCancelGuards.shouldCancelOnEscape(agentBusy)).toBe(expected)
        })
    })

    describe('handleComposerKeyDown', () => {
        let textarea: HTMLTextAreaElement

        beforeEach(() => {
            textarea = document.createElement('textarea')
            document.body.appendChild(textarea)
        })

        function dispatchFromTextarea(event: KeyboardEvent, options: ComposerShortcutsOptions): KeyboardEvent {
            textarea.addEventListener('keydown', (e) => handleComposerKeyDown(e, options))
            textarea.dispatchEvent(event)
            return event
        }

        it('cycles mode and prevents default on Shift+Tab from the textarea', () => {
            const options = makeOptions()
            const event = dispatchFromTextarea(keydown({ key: 'Tab', shiftKey: true }), options)
            expect(options.onModeChange).toHaveBeenCalledTimes(1)
            expect(options.onModeChange).toHaveBeenCalledWith('acceptEdits')
            expect(event.defaultPrevented).toBe(true)
        })

        it('ignores plain Tab', () => {
            const options = makeOptions()
            const event = dispatchFromTextarea(keydown({ key: 'Tab' }), options)
            expect(options.onModeChange).not.toHaveBeenCalled()
            expect(event.defaultPrevented).toBe(false)
        })

        it.each(['ctrlKey', 'metaKey', 'altKey'] as const)('ignores Shift+Tab with %s held', (modifier) => {
            const options = makeOptions()
            const init: KeyboardEventInit = { key: 'Tab', shiftKey: true }
            init[modifier] = true
            const event = dispatchFromTextarea(keydown(init), options)
            expect(options.onModeChange).not.toHaveBeenCalled()
            expect(event.defaultPrevented).toBe(false)
        })

        it('does not prevent default when Shift+Tab has no mode to cycle to', () => {
            const options = makeOptions({ modeOption: undefined })
            const event = dispatchFromTextarea(keydown({ key: 'Tab', shiftKey: true }), options)
            expect(options.onModeChange).not.toHaveBeenCalled()
            expect(event.defaultPrevented).toBe(false)
        })

        it('ignores Shift+Tab when the event target is not a textarea', () => {
            const options = makeOptions()
            const button = document.createElement('button')
            document.body.appendChild(button)
            button.addEventListener('keydown', (e) => handleComposerKeyDown(e, options))
            const event = keydown({ key: 'Tab', shiftKey: true })
            button.dispatchEvent(event)
            expect(options.onModeChange).not.toHaveBeenCalled()
            expect(event.defaultPrevented).toBe(false)
        })

        it('cancels the run and swallows Escape while the agent is busy', () => {
            const options = makeOptions({ agentBusy: true })
            const stopPropagation = jest.fn()
            const event = keydown({ key: 'Escape' })
            event.stopPropagation = stopPropagation
            dispatchFromTextarea(event, options)
            expect(options.onCancel).toHaveBeenCalledTimes(1)
            expect(event.defaultPrevented).toBe(true)
            expect(stopPropagation).toHaveBeenCalled()
        })

        it('leaves Escape alone when the agent is idle', () => {
            const options = makeOptions({ agentBusy: false })
            const event = dispatchFromTextarea(keydown({ key: 'Escape' }), options)
            expect(options.onCancel).not.toHaveBeenCalled()
            expect(event.defaultPrevented).toBe(false)
        })

        it('ignores Escape with a modifier held', () => {
            const options = makeOptions({ agentBusy: true })
            const event = dispatchFromTextarea(keydown({ key: 'Escape', metaKey: true }), options)
            expect(options.onCancel).not.toHaveBeenCalled()
            expect(event.defaultPrevented).toBe(false)
        })
    })

    describe('useComposerShortcuts', () => {
        function setup(initialOptions: ComposerShortcutsOptions): {
            container: HTMLDivElement
            textarea: HTMLTextAreaElement
            rerender: (options: ComposerShortcutsOptions) => void
            unmount: () => void
        } {
            const container = document.createElement('div')
            const textarea = document.createElement('textarea')
            container.appendChild(textarea)
            document.body.appendChild(container)
            const ref = { current: container }
            const { rerender, unmount } = renderHook(
                (options: ComposerShortcutsOptions) => useComposerShortcuts(ref, options),
                { initialProps: initialOptions }
            )
            return { container, textarea, rerender, unmount }
        }

        it('handles Shift+Tab bubbling from the textarea up to the container', () => {
            const options = makeOptions()
            const { textarea } = setup(options)
            const event = keydown({ key: 'Tab', shiftKey: true })
            textarea.dispatchEvent(event)
            expect(options.onModeChange).toHaveBeenCalledWith('acceptEdits')
            expect(event.defaultPrevented).toBe(true)
        })

        it('reads the latest options after a rerender without re-attaching', () => {
            const idle = makeOptions({ agentBusy: false })
            const { textarea, rerender } = setup(idle)
            const busy = makeOptions({ agentBusy: true })
            rerender(busy)
            textarea.dispatchEvent(keydown({ key: 'Escape' }))
            expect(idle.onCancel).not.toHaveBeenCalled()
            expect(busy.onCancel).toHaveBeenCalledTimes(1)
        })

        it('removes the listener on unmount', () => {
            const options = makeOptions({ agentBusy: true })
            const { textarea, unmount } = setup(options)
            unmount()
            textarea.dispatchEvent(keydown({ key: 'Escape' }))
            expect(options.onCancel).not.toHaveBeenCalled()
        })

        it('ignores Shift+Tab originating from a sibling button inside the container', () => {
            const options = makeOptions()
            const { container } = setup(options)
            const button = document.createElement('button')
            container.appendChild(button)
            const event = keydown({ key: 'Tab', shiftKey: true })
            button.dispatchEvent(event)
            expect(options.onModeChange).not.toHaveBeenCalled()
            expect(event.defaultPrevented).toBe(false)
        })
    })
})
