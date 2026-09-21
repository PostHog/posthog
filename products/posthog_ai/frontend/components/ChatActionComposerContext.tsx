import { createContext, type ReactNode, useContext } from 'react'

/**
 * The composer a suggested-action button drives. A surface that hosts a thread provides one for its
 * own composer (the runner wires `runInteractionLogic`, the Max panel wires its own input), so the
 * button never has to know which composer it sits above. Without a provider the buttons stay disabled.
 */
export interface ChatActionComposer {
    /** Puts the message in the composer and focuses it; an existing draft is kept above it. */
    insert: (message: string) => void
    /** Sends the message as the next turn. */
    send: (message: string) => void
    /** Why `send` is blocked right now (a draft in progress, a run stopping), or null when it can go. */
    sendDisabledReason: string | null
}

const ChatActionComposerContext = createContext<ChatActionComposer | null>(null)

export function ChatActionComposerProvider({
    value,
    children,
}: {
    value: ChatActionComposer
    children: ReactNode
}): JSX.Element {
    return <ChatActionComposerContext.Provider value={value}>{children}</ChatActionComposerContext.Provider>
}

export function useChatActionComposer(): ChatActionComposer | null {
    return useContext(ChatActionComposerContext)
}
