import { createContext, useContext } from 'react'

import type { EmailVariableContext, EmailVariableOption } from './emailVariables'

export interface EmailEditorContextValue {
    variableContext: EmailVariableContext
    variableOptions: EmailVariableOption[]
    pickImage: (
        onPicked: (image: {
            src: string
            alt?: string
            naturalWidth?: number | null
            naturalHeight?: number | null
            mediaId?: string
        }) => void
    ) => void
    openLinkEditor: () => void
}

export const EmailEditorContext = createContext<EmailEditorContextValue>({
    variableContext: { transactional: false, personProperties: null, extra: [] },
    variableOptions: [],
    pickImage: () => {},
    openLinkEditor: () => {},
})

export function useEmailEditorContext(): EmailEditorContextValue {
    return useContext(EmailEditorContext)
}
