import { createContext } from 'react'

import { EmailPreviewPerson } from 'scenes/hog-functions/email-templater/preview/emailPreview'

/** The person the canvas renders email steps as. Undefined while person previews are off. */
export const CanvasPreviewPersonContext = createContext<EmailPreviewPerson | null | undefined>(undefined)
