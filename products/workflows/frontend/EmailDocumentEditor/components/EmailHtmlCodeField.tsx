import { useEffect, useRef, useState } from 'react'

import { CodeEditor } from 'lib/monaco/CodeEditor'

export function EmailHtmlCodeField({
    html,
    onChange,
}: {
    html: string
    onChange: (html: string) => void
}): JSX.Element {
    const [draft, setDraft] = useState(html)
    const typed = useRef(html)

    // Each edit applies at once, so nothing waits on a block position that a move or another selection can change.
    // Only a change from elsewhere, such as undo or the larger editor, replaces what is typed here.
    useEffect(() => {
        if (html !== typed.current) {
            typed.current = html
            setDraft(html)
        }
    }, [html])

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
                        typed.current = next
                        setDraft(next)
                        onChange(next)
                    }}
                    options={{ minimap: { enabled: false }, wordWrap: 'on', lineNumbers: 'off', folding: false }}
                />
            </div>
        </div>
    )
}
