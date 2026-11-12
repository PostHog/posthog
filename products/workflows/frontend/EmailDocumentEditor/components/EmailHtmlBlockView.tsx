import { NodeSelection } from '@tiptap/pm/state'
import { NodeViewProps, NodeViewWrapper } from '@tiptap/react'
import clsx from 'clsx'
import { useEffect, useRef, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { CodeEditor } from 'lib/monaco/CodeEditor'

import { EmailBlockStyle, emailFontUrls, resolvePageStyle } from '../emailDocument'
import { isFullHtmlDocument, oldEditorCss } from '../renderEmailHtml'

// The email gives a fragment the page's font and no margin. A full document keeps whatever it sets.
function previewDocument(html: string, editor: NodeViewProps['editor']): string {
    if (isFullHtmlDocument(html)) {
        return html
    }
    const page = resolvePageStyle(editor.state.doc.attrs.page)
    const fonts = emailFontUrls(editor.state.doc.toJSON())
        .map((url) => `<link rel="stylesheet" href="${url.replace(/"/g, '&quot;')}" />`)
        .join('')
    const oldStyles = page.oldEditorStyles ? oldEditorCss(page) : ''
    return `${fonts}<style>body{margin:0;font-family:${page.fontFamily};font-size:${page.fontSize}px;line-height:${page.lineHeight}%;color:${page.textColor}}${oldStyles}</style>${html}`
}

export function EmailHtmlBlockView({ node, selected, updateAttributes, editor }: NodeViewProps): JSX.Element {
    const [editing, setEditing] = useState(false)
    const [draft, setDraft] = useState<string>(node.attrs.html)
    const [height, setHeight] = useState(60)
    const iframeRef = useRef<HTMLIFrameElement>(null)
    const style = (node.attrs.emailStyle ?? {}) as EmailBlockStyle
    const padding = style.padding

    // An empty block asks for its html once someone picks it, not whenever the email loads with one.
    const isEmptyAndPicked = !node.attrs.html && selected && editor.state.selection instanceof NodeSelection
    useEffect(() => {
        if (isEmptyAndPicked) {
            setEditing(true)
        }
    }, [isEmptyAndPicked])

    useEffect(() => {
        if (editing) {
            setDraft(node.attrs.html)
        }
    }, [editing, node.attrs.html])

    const srcDoc = previewDocument(node.attrs.html, editor)

    const measure = (): void => {
        const body = iframeRef.current?.contentDocument?.documentElement
        if (body) {
            setHeight(Math.max(40, body.scrollHeight))
        }
    }

    return (
        <NodeViewWrapper
            className={clsx(
                'email-canvas-html',
                selected && editor.state.selection instanceof NodeSelection && 'email-canvas-selected'
            )}
            data-drag-handle
            style={{
                padding: padding
                    ? `${padding.top}px ${padding.right}px ${padding.bottom}px ${padding.left}px`
                    : undefined,
            }}
        >
            <div contentEditable={false} className="relative group">
                {node.attrs.html ? (
                    // allow-same-origin only lets the height be read. Without allow-scripts nothing in it can run.
                    <iframe
                        ref={iframeRef}
                        title="Custom HTML block"
                        sandbox="allow-same-origin"
                        srcDoc={srcDoc}
                        onLoad={measure}
                        className="w-full border-0 pointer-events-none block"
                        style={{ height }}
                    />
                ) : (
                    <div className="email-canvas-image-empty">Empty HTML block</div>
                )}
                <div className="email-canvas-html-edit">
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        data-attr="email-editor-html-edit"
                        onClick={() => setEditing(true)}
                    >
                        Edit HTML
                    </LemonButton>
                </div>
            </div>
            {editing ? (
                <LemonModal
                    isOpen
                    onClose={() => setEditing(false)}
                    onAfterClose={() => editor.commands.focus()}
                    title="Edit HTML"
                    width={800}
                    footer={
                        <>
                            <LemonButton type="secondary" onClick={() => setEditing(false)}>
                                Cancel
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                data-attr="email-editor-html-save"
                                onClick={() => {
                                    updateAttributes({ html: draft })
                                    setEditing(false)
                                }}
                            >
                                Apply
                            </LemonButton>
                        </>
                    }
                >
                    <CodeEditor
                        language="html"
                        height={400}
                        value={draft}
                        onChange={(value) => setDraft(value ?? '')}
                        options={{ minimap: { enabled: false }, wordWrap: 'on' }}
                    />
                </LemonModal>
            ) : null}
        </NodeViewWrapper>
    )
}
