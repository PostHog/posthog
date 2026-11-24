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
    /** The email is one HTML block that goes out as written, so the canvas shows it without the page around it. */
    sentAsWritten: boolean
}

export const EmailEditorContext = createContext<EmailEditorContextValue>({
    variableContext: { transactional: false, personProperties: null, extra: [] },
    variableOptions: [],
    pickImage: () => {},
    openLinkEditor: () => {},
    sentAsWritten: false,
})

export function useEmailEditorContext(): EmailEditorContextValue {
    return useContext(EmailEditorContext)
}
