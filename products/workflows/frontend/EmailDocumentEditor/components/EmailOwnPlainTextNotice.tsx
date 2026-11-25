import type { Editor } from '@tiptap/react'
import { useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonButton } from '@posthog/lemon-ui'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { emailTemplaterLogic } from 'scenes/hog-functions/email-templater/emailTemplaterLogic'

/** Shown while an email keeps the plain text it came with, because edits to the email don't reach that text. */
export function EmailOwnPlainTextNotice({ editor }: { editor: Editor }): JSX.Element {
    const { logicProps } = useValues(emailTemplaterLogic)
    return (
        <LemonButton
            size="xsmall"
            data-attr="email-editor-own-plain-text"
            tooltip="This email came with its own plain text. Editing the email doesn't change it."
            onClick={() =>
                LemonDialog.open({
                    title: 'Update the plain text from this email?',
                    maxWidth: '36rem',
                    description:
                        "This email came with its own plain text, which stays the same when you edit the email. Updating replaces it with text written from the email, now and on every edit. You can't undo this.",
                    content: (
                        <pre className="ph-no-capture max-h-60 overflow-auto whitespace-pre-wrap text-xs border rounded p-2 mb-0">
                            {logicProps.value?.text}
                        </pre>
                    ),
                    primaryButton: {
                        children: 'Update plain text',
                        'data-attr': 'email-editor-update-plain-text',
                        onClick: () => {
                            // pinned: analytics event name and property, renaming breaks dashboards
                            posthog.capture('email editor plain text updated', { email_type: logicProps.type })
                            // Undo can't bring the old text back, so it doesn't bring back keeping it either.
                            editor.view.dispatch(
                                editor.state.tr.setDocAttribute('ownPlainText', false).setMeta('addToHistory', false)
                            )
                        },
                    },
                    secondaryButton: { children: 'Keep it' },
                })
            }
        >
            Plain text isn't updated
        </LemonButton>
    )
}
