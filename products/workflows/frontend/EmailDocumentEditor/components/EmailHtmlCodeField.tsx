import { useEffect, useRef, useState } from 'react'

import { CodeEditor } from 'lib/monaco/CodeEditor'

const APPLY_DELAY_MS = 300

export function EmailHtmlCodeField({
    html,
    onChange,
}: {
    html: string
    onChange: (html: string) => void
}): JSX.Element {
    const [draft, setDraft] = useState(html)
    const pending = useRef<ReturnType<typeof setTimeout> | null>(null)
    const latest = useRef({ draft: html, onChange })
    latest.current.onChange = onChange

    // A change from elsewhere, such as undo or the larger editor, replaces the draft unless one is still being applied.
    useEffect(() => {
        if (!pending.current) {
            setDraft(html)
        }
    }, [html])

    // Picking another block or closing the panel unmounts the field, so an edit still waiting is applied then.
    useEffect(
        () => () => {
            if (pending.current) {
                clearTimeout(pending.current)
                pending.current = null
                latest.current.onChange(latest.current.draft)
            }
        },
        []
    )

    return (
        <div className="flex flex-col gap-1" data-attr="email-editor-html-code">
            <span className="text-xs text-secondary">HTML</span>
            <div className="border rounded overflow-hidden">
                <CodeEditor
                    language="html"
                    height={320}
                    value={draft}
                    onChange={(value) => {
                        const next = value ?? ''
                        setDraft(next)
                        latest.current.draft = next
                        if (pending.current) {
                            clearTimeout(pending.current)
                        }
                        pending.current = setTimeout(() => {
                            pending.current = null
                            onChange(next)
                        }, APPLY_DELAY_MS)
                    }}
                    options={{ minimap: { enabled: false }, wordWrap: 'on', lineNumbers: 'off', folding: false }}
                />
            </div>
        </div>
    )
}
