import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useMemo, useState } from 'react'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { withInertLinks } from 'scenes/hog-functions/email-templater/emailPreviewHtml'
import { emailTemplaterLogic } from 'scenes/hog-functions/email-templater/emailTemplaterLogic'

import { emailDocumentFromValue } from '../emailDocument'
import { renderEmailHtml } from '../renderEmailHtml'

function captureSwitch(to: 'old' | 'new', emailType: string, source: string): void {
    // pinned: analytics event name and properties, renaming breaks dashboards
    posthog.capture('email editor switched', { to, email_type: emailType, source })
}

/** Next to the new editor's other controls: the way back, for anyone who needs it. */
function UseOldButton(): JSX.Element {
    const { logicProps, convertedEmailDocument } = useValues(emailTemplaterLogic)
    const { setPrefersOldEmailEditor } = useActions(emailTemplaterLogic)
    const savedInNewEditor = !!emailDocumentFromValue(logicProps.value).document
    const switchToOld = (): void => {
        captureSwitch(
            'old',
            logicProps.type,
            savedInNewEditor ? 'document' : convertedEmailDocument ? 'converted' : 'new'
        )
        setPrefersOldEmailEditor(true)
    }
    return (
        <LemonButton
            size="xsmall"
            data-attr="email-editor-use-old"
            onClick={() => {
                if (!savedInNewEditor) {
                    switchToOld()
                    return
                }
                LemonDialog.open({
                    title: 'Use the old editor?',
                    description:
                        "This email was made in the new editor. The old one opens it with the same blocks, and saving there replaces the new editor's version. Changes you haven't saved here won't carry over.",
                    primaryButton: { children: 'Use the old editor', onClick: switchToOld },
                    secondaryButton: { children: 'Keep the new editor' },
                })
            }}
        >
            Use old editor
        </LemonButton>
    )
}

/** Shown on an old-editor email in the new editor, where it's converted but not yet saved. */
function ConvertedNotice(): JSX.Element | null {
    const { logicProps, emailConversion, convertedEmailDocument } = useValues(emailTemplaterLogic)
    const [comparing, setComparing] = useState(false)
    const html = logicProps.value?.html ?? ''
    const convertedHtml = useMemo(
        () => (comparing && convertedEmailDocument ? renderEmailHtml(convertedEmailDocument.doc) : ''),
        [comparing, convertedEmailDocument]
    )
    useEffect(() => {
        if (comparing) {
            // pinned: analytics event name and property, renaming breaks dashboards
            posthog.capture('email editor conversion compared', { email_type: logicProps.type })
        }
    }, [comparing, logicProps.type])
    if (!convertedEmailDocument) {
        return null
    }
    return (
        <>
            <div
                className="flex items-center justify-between gap-2 px-2 py-1 border-b shrink-0 flex-wrap"
                data-attr="email-editor-converted-notice"
            >
                <span className="text-xs text-secondary">
                    This email was made in the old editor. Nothing changes until you edit it
                    {emailConversion?.notKept.length
                        ? `, and editing won't keep ${emailConversion.notKept.join(', ')}.`
                        : '.'}
                </span>
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    data-attr="email-editor-compare"
                    onClick={() => setComparing(true)}
                >
                    Compare versions
                </LemonButton>
            </div>
            <LemonModal
                isOpen={comparing}
                onClose={() => setComparing(false)}
                title="The email now and in the new editor"
                width={1100}
            >
                <div className="grid grid-cols-2 gap-2">
                    <div className="flex flex-col gap-1 min-w-0">
                        <span className="text-xs font-semibold">Now</span>
                        <iframe
                            title="Current email"
                            sandbox=""
                            srcDoc={withInertLinks(html)}
                            className="w-full h-[60vh] border bg-white"
                        />
                    </div>
                    <div className="flex flex-col gap-1 min-w-0">
                        <span className="text-xs font-semibold">New editor</span>
                        <iframe
                            title="Converted email"
                            sandbox=""
                            srcDoc={withInertLinks(convertedHtml)}
                            className="w-full h-[60vh] border bg-white"
                            data-attr="email-editor-convert-preview"
                        />
                    </div>
                </div>
            </LemonModal>
        </>
    )
}

/** Above the old editor: why this email is here, and the way to the new one when it can open there. */
function OldEditorBar(): JSX.Element | null {
    const { logicProps, prefersOldEmailEditor, emailConversion } = useValues(emailTemplaterLogic)
    const { setPrefersOldEmailEditor } = useActions(emailTemplaterLogic)
    if (prefersOldEmailEditor) {
        return (
            <div
                className="flex items-center justify-between gap-2 px-2 py-1 border-b shrink-0 flex-wrap"
                data-attr="email-editor-old-bar"
            >
                <span className="text-xs text-secondary">You're using the old editor.</span>
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    data-attr="email-editor-use-new"
                    onClick={() => {
                        captureSwitch('new', logicProps.type, 'old')
                        setPrefersOldEmailEditor(false)
                    }}
                >
                    Use new editor
                </LemonButton>
            </div>
        )
    }
    if (emailConversion?.unsupported.length) {
        return (
            <div data-attr="email-editor-convert-unsupported">
                <LemonBanner type="info" className="rounded-none">
                    This email stays on the old editor because the new one doesn't support{' '}
                    {emailConversion.unsupported.join(', ')} yet.
                </LemonBanner>
            </div>
        )
    }
    return null
}

export const EmailEditorSwitch = { UseOldButton, ConvertedNotice, OldEditorBar }
