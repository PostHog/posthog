import { KeyboardShortcut } from 'lib/components/KeyboardShortcut/KeyboardShortcut'
import { useEventListener } from 'lib/hooks/useEventListener'
import { LemonRadio, LemonRadioOption } from 'lib/lemon-ui/LemonRadio'

import { HotKey } from '~/types'

const DIGIT_HOTKEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9'] as const satisfies readonly HotKey[]

export interface HotkeyRadioOption<T extends React.Key> {
    value: T
    label: string
}

interface HotkeyRadioProps<T extends React.Key> {
    value: T | null | undefined
    onChange: (value: T) => void
    /** At most nine options get a digit shortcut; any past that render without one. */
    options: readonly HotkeyRadioOption<T>[]
}

// A digit typed into a text field is content, not a shortcut. Radio and checkbox inputs are not
// text fields, so a digit still picks an option after one of them was clicked.
function isTextEntryTarget(target: EventTarget | null): boolean {
    if (!(target instanceof HTMLElement)) {
        return false
    }
    if (target.isContentEditable || target instanceof HTMLTextAreaElement) {
        return true
    }
    return target instanceof HTMLInputElement && !['radio', 'checkbox', 'button', 'submit'].includes(target.type)
}

/**
 * A radio group where the digit keys 1..9 pick the matching option, with a keycap in front of each
 * label. The listener sits on `window` while the group is mounted, so it works from wherever focus
 * is in the dialog except a text field. Modifier chords are left to the browser.
 */
export function HotkeyRadio<T extends React.Key>({ value, onChange, options }: HotkeyRadioProps<T>): JSX.Element {
    useEventListener(
        'keydown',
        (event) => {
            if (event.metaKey || event.ctrlKey || event.altKey || isTextEntryTarget(event.target)) {
                return
            }
            const index = (DIGIT_HOTKEYS as readonly string[]).indexOf(event.key)
            const option = index >= 0 ? options[index] : undefined
            if (!option) {
                return
            }
            event.preventDefault()
            onChange(option.value)
        },
        window,
        [options, onChange]
    )

    const radioOptions: LemonRadioOption<T>[] = options.map((option, index) => {
        const hotkey = DIGIT_HOTKEYS[index]
        return {
            value: option.value,
            label: hotkey ? (
                <span className="inline-flex items-center gap-2">
                    <KeyboardShortcut {...{ [hotkey]: true }} />
                    {option.label}
                </span>
            ) : (
                option.label
            ),
        }
    })

    return <LemonRadio value={value ?? undefined} onChange={onChange} options={radioOptions} />
}
