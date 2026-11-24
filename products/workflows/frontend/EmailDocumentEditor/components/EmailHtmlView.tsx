import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { IconCopy } from '@posthog/icons'
import { LemonBanner, LemonButton, Spinner } from '@posthog/lemon-ui'

import { CodeEditor, CodeEditorProps } from 'lib/monaco/CodeEditor'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { emailTemplaterLogic } from 'scenes/hog-functions/email-templater/emailTemplaterLogic'

import { emailHtmlViewLogic } from '../emailHtmlViewLogic'

const VIEWER_OPTIONS: CodeEditorProps['options'] = {
    readOnly: true,
    minimap: { enabled: false },
    wordWrap: 'on',
    scrollBeyondLastLine: false,
}

/** The html a save stores, to read and copy. Nothing here changes the email. */
export function EmailHtmlView(): JSX.Element {
    const { reading } = useValues(emailHtmlViewLogic)
    const { latestEditUnsaved, logicProps } = useValues(emailTemplaterLogic)
    const { readLatestEdit } = useActions(emailHtmlViewLogic)
    const emailType = logicProps.type
    const savedHtml = logicProps.value?.html ?? ''

    useEffect(() => {
        // pinned: analytics event name and properties, renaming breaks dashboards
        !reading && posthog.capture('email editor html viewed', { email_type: emailType, success: !latestEditUnsaved })
    }, [reading, latestEditUnsaved, emailType])

    if (reading) {
        return (
            <div className="flex justify-center p-8">
                <Spinner className="text-2xl" />
            </div>
        )
    }
    if (latestEditUnsaved) {
        return (
            <div className="p-2">
                <LemonBanner type="error" action={{ children: 'Try again', onClick: () => readLatestEdit() }}>
                    Couldn't read your latest change, so its HTML can't be shown. Your changes are still in the editor.
                </LemonBanner>
            </div>
        )
    }
    if (!savedHtml) {
        return (
            <p className="text-secondary m-0 p-8 text-center">
                {logicProps.value?.text
                    ? 'This email goes out as plain text, so it has no HTML.'
                    : 'This email has no HTML yet. Add some content in the editor first.'}
            </p>
        )
    }
    return (
        <div className="ph-no-capture flex flex-col flex-1 min-h-0 gap-2 p-2" data-attr="email-editor-html-view">
            <div className="flex items-center gap-2 flex-wrap">
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    icon={<IconCopy />}
                    data-attr="email-editor-html-copy"
                    onClick={() => {
                        void copyToClipboard(savedHtml, 'email HTML').then((copied) => {
                            if (copied) {
                                // pinned: analytics event name and property, renaming breaks dashboards
                                posthog.capture('email editor html copied', { email_type: emailType })
                            }
                        })
                    }}
                >
                    Copy HTML
                </LemonButton>
                <span className="text-xs text-secondary">Read-only. Variables and conditions show as written.</span>
            </div>
            <div className="relative flex-1 min-h-80 border rounded overflow-hidden">
                <div className="absolute inset-0">
                    <CodeEditor language="html" className="h-full" value={savedHtml} options={VIEWER_OPTIONS} />
                </div>
            </div>
        </div>
    )
}
