import { act, renderHook } from '@testing-library/react'
import { useRef, useState } from 'react'

import { useDebouncedDraft } from './useDebouncedDraft'

describe('useDebouncedDraft', () => {
    beforeEach(() => jest.useFakeTimers())
    afterEach(() => jest.useRealTimers())

    it.each([
        { settled: false, accepted: true },
        { settled: false, accepted: false },
        { settled: true, accepted: true },
    ])('submits the latest draft with settled=$settled and accepted=$accepted', ({ settled, accepted }) => {
        const send = jest.fn()
        const { result, unmount } = renderHook(() => {
            const [saved, setSaved] = useState('')
            const current = useRef(saved)
            const sync = (next: string): void => {
                current.current = next
                setSaved(next)
            }
            const draft = useDebouncedDraft(saved, sync)
            return {
                draft,
                submit: () =>
                    draft.submit(() => {
                        send(current.current)
                        if (accepted) {
                            sync('')
                        }
                    }),
            }
        })

        act(() => result.current.draft.onChange('follow-up message'))
        if (settled) {
            act(() => jest.advanceTimersByTime(150))
        }
        act(() => result.current.submit())

        expect(send).toHaveBeenCalledWith('follow-up message')
        expect(result.current.draft.value).toBe(accepted ? '' : 'follow-up message')
        act(() => jest.advanceTimersByTime(150))
        expect(result.current.draft.value).toBe(accepted ? '' : 'follow-up message')
        unmount()
    })
})
