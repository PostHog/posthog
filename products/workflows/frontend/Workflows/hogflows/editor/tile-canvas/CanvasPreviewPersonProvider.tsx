import { useValues } from 'kea'
import { useContext } from 'react'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { emailPreviewPersonLogic } from 'scenes/hog-functions/email-templater/preview/emailPreviewPersonLogic'
import { EmailPreviewScopeContext } from 'scenes/hog-functions/email-templater/preview/EmailPreviewScopeContext'

import { CanvasPreviewPersonContext } from './CanvasPreviewPersonContext'

function PreviewPersonScope({ children }: { children: React.ReactNode }): JSX.Element {
    const scope = useContext(EmailPreviewScopeContext)
    const { previewPerson } = useValues(emailPreviewPersonLogic({ scope }))
    return <CanvasPreviewPersonContext.Provider value={previewPerson}>{children}</CanvasPreviewPersonContext.Provider>
}

/** Renders the canvas's email steps as the workflow's preview person, while person previews are on. */
export function CanvasPreviewPersonProvider({ children }: { children: React.ReactNode }): JSX.Element {
    const enabled = useFeatureFlag('WORKFLOWS_EMAIL_PERSON_PREVIEW')
    return enabled ? <PreviewPersonScope>{children}</PreviewPersonScope> : <>{children}</>
}
