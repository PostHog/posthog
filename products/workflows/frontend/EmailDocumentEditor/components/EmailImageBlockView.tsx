import { NodeSelection } from '@tiptap/pm/state'
import { NodeViewProps, NodeViewWrapper } from '@tiptap/react'
import clsx from 'clsx'
import { useRef, useState } from 'react'

import { IconImage } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { EmailBlockStyle } from '../emailDocument'
import { AUTOMATIC_CHANGE_META } from '../emailEditorAdapter'
import { useEmailEditorContext } from '../emailEditorContext'

export function EmailImageBlockView({ node, selected, updateAttributes, editor, getPos }: NodeViewProps): JSX.Element {
    const { pickImage } = useEmailEditorContext()
    const [failed, setFailed] = useState<string | null>(null)
    const [dragWidth, setDragWidth] = useState<number | null>(null)
    const imageRef = useRef<HTMLImageElement>(null)
    const style = (node.attrs.emailStyle ?? {}) as EmailBlockStyle
    const { src, alt, naturalWidth } = node.attrs
    const width = dragWidth ?? style.width ?? naturalWidth ?? undefined
    const padding = style.padding
    const align = style.textAlign ?? 'left'
    const blockSelected = selected && editor.state.selection instanceof NodeSelection

    const startResize = (event: React.MouseEvent): void => {
        event.preventDefault()
        event.stopPropagation()
        const startX = event.clientX
        const startWidth = imageRef.current?.getBoundingClientRect().width ?? 0
        const direction = align === 'right' ? -1 : 1
        let latest = startWidth
        const onMove = (moveEvent: MouseEvent): void => {
            latest = Math.max(
                24,
                Math.round(startWidth + direction * (moveEvent.clientX - startX) * (align === 'center' ? 2 : 1))
            )
            setDragWidth(latest)
        }
        const onUp = (): void => {
            window.removeEventListener('mousemove', onMove)
            window.removeEventListener('mouseup', onUp)
            setDragWidth(null)
            const pos = getPos()
            if (typeof pos === 'number') {
                const current = editor.state.doc.nodeAt(pos)
                editor.view.dispatch(
                    editor.state.tr.setNodeAttribute(pos, 'emailStyle', { ...current?.attrs.emailStyle, width: latest })
                )
            }
        }
        window.addEventListener('mousemove', onMove)
        window.addEventListener('mouseup', onUp)
    }

    return (
        <NodeViewWrapper
            className={clsx('email-canvas-image', blockSelected && 'email-canvas-selected')}
            data-drag-handle
            style={{
                textAlign: align,
                padding: padding
                    ? `${padding.top}px ${padding.right}px ${padding.bottom}px ${padding.left}px`
                    : undefined,
            }}
        >
            {!src ? (
                <div className="email-canvas-image-empty" contentEditable={false}>
                    <IconImage className="text-2xl" />
                    <LemonButton
                        size="small"
                        type="secondary"
                        data-attr="email-editor-image-choose"
                        onClick={() => pickImage((image) => updateAttributes(image))}
                    >
                        Choose an image
                    </LemonButton>
                </div>
            ) : failed === src ? (
                <div className="email-canvas-image-empty" contentEditable={false}>
                    <IconImage className="text-2xl" />
                    <span>This image couldn't be loaded. Recipients may not see it either.</span>
                    <LemonButton
                        size="small"
                        type="secondary"
                        onClick={() => pickImage((image) => updateAttributes(image))}
                    >
                        Replace image
                    </LemonButton>
                </div>
            ) : (
                <span className="email-canvas-image-frame" contentEditable={false}>
                    <img
                        ref={imageRef}
                        src={src}
                        alt={alt}
                        draggable={false}
                        onError={() => setFailed(src)}
                        onLoad={(event) => {
                            // Links and older uploads don't record a size, and the email needs one for Outlook.
                            // Recording it isn't an edit, so an email nobody touched isn't saved because of it.
                            const pos = typeof getPos === 'function' ? getPos() : undefined
                            if (!naturalWidth && typeof pos === 'number') {
                                editor.view.dispatch(
                                    editor.state.tr
                                        .setNodeMarkup(pos, undefined, {
                                            ...node.attrs,
                                            naturalWidth: event.currentTarget.naturalWidth,
                                            naturalHeight: event.currentTarget.naturalHeight,
                                        })
                                        .setMeta(AUTOMATIC_CHANGE_META, true)
                                        .setMeta('addToHistory', false)
                                )
                            }
                        }}
                        style={{
                            width: width ? `${width}px` : undefined,
                            borderRadius: style.borderRadius ? `${style.borderRadius}px` : undefined,
                        }}
                    />
                    {blockSelected ? (
                        <button
                            type="button"
                            className="email-canvas-image-resize"
                            aria-label="Resize image"
                            onMouseDown={startResize}
                            data-attr="email-editor-image-resize"
                        />
                    ) : null}
                </span>
            )}
        </NodeViewWrapper>
    )
}
