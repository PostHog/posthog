import { NodeSelection } from '@tiptap/pm/state'
import { NodeViewProps, NodeViewWrapper } from '@tiptap/react'
import clsx from 'clsx'
import { useEffect, useRef, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { CodeEditor } from 'lib/monaco/CodeEditor'

import { EmailBlockStyle, emailFontUrls, resolvePageStyle } from '../emailDocument'
import { useEmailEditorContext } from '../emailEditorContext'
import { isFullHtmlDocument, oldEditorCss } from '../renderEmailHtml'

// Past the usual 600px and 640px phone breakpoints, so the desktop layout shows even in a narrow editor.
const MIN_DESKTOP_WIDTH = 660

// The email gives a fragment the page's font and no margin. A full document keeps whatever it sets.
function previewDocument(html: string, editor: NodeViewProps['editor'], sentAsWritten: boolean): string {
    if (sentAsWritten || isFullHtmlDocument(html)) {
        return html
    }
    const page = resolvePageStyle(editor.state.doc.attrs.page)
    const fonts = emailFontUrls(editor.state.doc.toJSON())
        .map((url) => `<link rel="stylesheet" href="${url.replace(/"/g, '&quot;')}" />`)
        .join('')
    const oldStyles = page.oldEditorStyles ? oldEditorCss(page) : ''
    // A row kept from the old editor lays out with the page CSS it was exported with.
    const pageCss = page.globalCss.replace(/<\/?style/gi, '')
    return `${fonts}<style>body{margin:0;font-family:${page.fontFamily};font-size:${page.fontSize}px;line-height:${page.lineHeight}%;color:${page.textColor}}${oldStyles}${pageCss}</style>${html}`
}

export function EmailHtmlBlockView({ node, selected, updateAttributes, editor }: NodeViewProps): JSX.Element {
    const { sentAsWritten } = useEmailEditorContext()
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

    const srcDoc = previewDocument(node.attrs.html, editor, sentAsWritten)

    const measure = (): void => {
        const iframe = iframeRef.current
        const root = iframe?.contentDocument?.documentElement
        if (!iframe || !root) {
            return
        }
        // Back to the smallest width first, so a wider email that was edited to be narrower shrinks again.
        iframe.style.minWidth = sentAsWritten ? `${MIN_DESKTOP_WIDTH}px` : ''
        if (sentAsWritten) {
            iframe.style.minWidth = `${Math.max(MIN_DESKTOP_WIDTH, root.scrollWidth)}px`
        }
        // The document's own height: its scroll height never drops below the frame's, so a short block kept the default.
        setHeight(Math.max(20, Math.ceil(root.getBoundingClientRect().height)))
    }
    const measureRef = useRef(measure)
    measureRef.current = measure

    // The email reflows when the editor gets wider or narrower, or when a block next to it puts it in the page's body.
    const hasHtml = !!node.attrs.html
    useEffect(() => {
        const iframe = iframeRef.current
        if (!iframe) {
            return
        }
        const observer = new ResizeObserver(() => measureRef.current())
        observer.observe(iframe)
        return () => observer.disconnect()
    }, [hasHtml, sentAsWritten])

    return (
        <NodeViewWrapper
            className={clsx(
                'email-canvas-html',
                // Grows with a wide email, so its outline and buttons do too.
                sentAsWritten && 'w-fit min-w-full',
                selected && editor.state.selection instanceof NodeSelection && 'email-canvas-selected'
            )}
            data-drag-handle
            style={{
                padding:
                    padding && !sentAsWritten
                        ? `${padding.top}px ${padding.right}px ${padding.bottom}px ${padding.left}px`
                        : undefined,
            }}
        >
            <div contentEditable={false} className="relative group" onDoubleClick={() => setEditing(true)}>
                {hasHtml ? (
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
