import { createContext, useContext } from 'react'

export type ThreadSkin = 'lemon' | 'quill'

/**
 * The skin of the thread a presenter renders in, set by `ThreadView`'s `skin` prop. Shared presenters
 * (`Activity`, `ThreadRow`, `ThreadActivityGroup`, `RunAlertActivity`, `PullRequestCard`,
 * `TurnFeedbackActions`) read it to pick their quill skin, so the tool registry's renderers and a
 * consumer's turn trailers never need to know which thread hosts them.
 */
export const ThreadSkinContext = createContext<ThreadSkin>('lemon')

export function useQuillThread(): boolean {
    return useContext(ThreadSkinContext) === 'quill'
}
