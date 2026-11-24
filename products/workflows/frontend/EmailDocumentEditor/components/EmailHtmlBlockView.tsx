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
// An email can ask for any width, and a frame that wide would only slow the tab down.
const MAX_WIDTH = 4000
const MIN_HEIGHT = 60

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
    const [height, setHeight] = useState(MIN_HEIGHT)
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
        const holder = iframe.parentElement
        const scroller = iframe.closest('.EmailDocumentEditor__scroll')
        const scrollLeft = scroller?.scrollLeft ?? 0
        // Keeps the canvas's scroll position and scrollbar while the frame is small.
        holder?.style.setProperty('min-height', `${iframe.offsetHeight}px`)
        // A document never reports less than the frame's own size, so it's measured in a small frame first. Otherwise the
        // frame couldn't shrink again, and an email as tall as its window would grow with every measurement.
        iframe.style.height = `${MIN_HEIGHT}px`
        iframe.style.minWidth = ''
        if (sentAsWritten) {
            // Both, because the app caps the width at the canvas and only the min width gets past that.
            iframe.style.width = `${MIN_DESKTOP_WIDTH}px`
            iframe.style.minWidth = `${MIN_DESKTOP_WIDTH}px`
            const fitEmail = (): void => {
                iframe.style.minWidth = `${Math.min(MAX_WIDTH, Math.max(MIN_DESKTOP_WIDTH, root.scrollWidth))}px`
            }
            fitEmail()
            iframe.style.width = ''
            // The room the canvas gives can switch the email to a wider layout.
            if (root.scrollWidth > iframe.clientWidth) {
                fitEmail()
            }
        }
        let measured = Math.max(20, Math.ceil(root.getBoundingClientRect().height))
        // Html and body with a height of 100% are only as tall as the frame, with the email overflowing them.
        if (sentAsWritten && root.scrollHeight > MIN_HEIGHT) {
            measured = Math.max(measured, root.scrollHeight)
        }
        iframe.style.height = `${measured}px`
        holder?.style.removeProperty('min-height')
        if (scroller) {
            scroller.scrollLeft = scrollLeft
        }
        setHeight(measured)
    }
    const measureRef = useRef(measure)
    measureRef.current = measure

    // Html sent as written reflows with the editor's width, such as when the style panel opens.
    const hasHtml = !!node.attrs.html
    useEffect(() => {
        measureRef.current()
        const canvas = iframeRef.current?.closest('.ProseMirror')
        if (!sentAsWritten || !canvas) {
            return
        }
        let width = canvas.clientWidth
        const observer = new ResizeObserver(() => {
            if (canvas.clientWidth !== width) {
                width = canvas.clientWidth
                measureRef.current()
            }
        })
        observer.observe(canvas)
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
                        // Its scrollbar would take width while the frame is measured small.
                        scrolling="no"
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
