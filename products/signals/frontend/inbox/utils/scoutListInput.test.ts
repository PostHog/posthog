import type { KeyboardEvent } from 'react'

import { scoutListInputKeyDown } from './scoutListInput'

describe('scoutListInputKeyDown', () => {
    const keyEvent = (key: string, isComposing: boolean): KeyboardEvent<HTMLInputElement> =>
        ({ key, preventDefault: jest.fn(), nativeEvent: { isComposing } }) as unknown as KeyboardEvent<HTMLInputElement>

    it('commits on Enter and comma, but not while an IME composition is active', () => {
        // An IME confirms its composition with Enter; committing then would capture the unfinished
        // pre-composition text. Enter and comma commit only once the composition has ended.
        const onCommit = jest.fn()
        const handler = scoutListInputKeyDown('bücher.example', onCommit)

        handler(keyEvent('Enter', true))
        expect(onCommit).not.toHaveBeenCalled()

        handler(keyEvent('Enter', false))
        handler(keyEvent(',', false))
        expect(onCommit).toHaveBeenCalledTimes(2)
    })
})
