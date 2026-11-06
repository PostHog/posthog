import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useMemo, useState } from 'react'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { withInertLinks } from 'scenes/hog-functions/email-templater/emailPreviewHtml'
import { emailTemplaterLogic } from 'scenes/hog-functions/email-templater/emailTemplaterLogic'

import { renderEmailHtml } from '../renderEmailHtml'
import { unlayerToEmailDocument } from '../unlayerToEmailDocument'

/** The way off the old editor. It shows both versions, and nothing changes until a person accepts. */
export function EmailEditorConversionPrompt(): JSX.Element {
    const { logicProps } = useValues(emailTemplaterLogic)
    const { switchToDocumentEditor } = useActions(emailTemplaterLogic)
    const [open, setOpen] = useState(false)
    const design = logicProps.value?.design as Record<string, any> | null | undefined
    const html = logicProps.value?.html ?? ''

    const conversion = useMemo(() => (open ? unlayerToEmailDocument(design, html) : null), [open, design, html])
    const convertedHtml = useMemo(
        () => (conversion?.document ? renderEmailHtml(conversion.document.doc) : ''),
        [conversion]
    )

    useEffect(() => {
        if (conversion) {
            // pinned: analytics event name and properties, renaming breaks dashboards
            posthog.capture('email editor conversion previewed', {
                convertible: !!conversion.document,
                unsupported: conversion.unsupported,
            })
        }
    }, [conversion])

    return (
        <>
            <div className="flex items-center justify-between gap-2 px-2 py-1 border-b shrink-0 flex-wrap">
                <span className="text-xs text-secondary">
                    This email uses the old editor. New emails use the new one.
                </span>
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    data-attr="email-editor-try-new"
                    onClick={() => setOpen(true)}
                >
                    Try the new editor
                </LemonButton>
            </div>
            <LemonModal
                isOpen={open}
                onClose={() => setOpen(false)}
                title="Move this email to the new editor"
                width={1100}
                footer={
                    <>
                        <LemonButton type="secondary" onClick={() => setOpen(false)}>
                            Keep the old editor
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            data-attr="email-editor-convert-accept"
                            disabledReason={conversion?.document ? undefined : "This email can't be moved yet"}
                            onClick={() => {
                                if (conversion?.document) {
                                    posthog.capture('email editor conversion accepted')
                                    switchToDocumentEditor(conversion.document)
                                    setOpen(false)
                                }
                            }}
                        >
                            Use the new editor
                        </LemonButton>
                    </>
                }
            >
                {conversion && !conversion.document ? (
                    <div data-attr="email-editor-convert-unsupported">
                        <LemonBanner type="info">
                            This email stays on the old editor because the new one doesn't support{' '}
                            {conversion.unsupported.join(', ')} yet. Nothing has changed.
                        </LemonBanner>
                    </div>
                ) : (
                    <div className="flex flex-col gap-2">
                        <p className="m-0 text-secondary">
                            Check that the new version looks right. Moving changes how this email is stored, and it may
                            look slightly different. Duplicate the template first if you want to keep a copy.
                        </p>
                        {conversion?.notKept.length ? (
                            <LemonBanner type="warning">
                                The new version won't keep {conversion.notKept.join(', ')}.
                            </LemonBanner>
                        ) : null}
                        <div className="grid grid-cols-2 gap-2">
                            <div className="flex flex-col gap-1 min-w-0">
                                <span className="text-xs font-semibold">Current</span>
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
                    </div>
                )}
            </LemonModal>
        </>
    )
}
