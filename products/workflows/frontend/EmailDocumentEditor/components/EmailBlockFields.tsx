import type { Editor } from '@tiptap/core'

import { IconImage } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonInput } from '@posthog/lemon-ui'

import { enclosingColumns, selectedBlock, setBlockAttribute, setBlockStyle } from '../emailCommands'
import { EmailBlockStyle, EmailSides, resolvePageStyle } from '../emailDocument'
import { useEmailEditorContext } from '../emailEditorContext'
import { EmailBoxFields } from './EmailBoxFields'
import { EmailColumnsFields } from './EmailColumnsFields'
import { EmailTextFields } from './EmailTextFields'
import { EmailAlignField } from './fields/EmailAlignField'
import { EmailColorField } from './fields/EmailColorField'
import { EmailFieldRow } from './fields/EmailFieldRow'
import { EmailNumberField } from './fields/EmailNumberField'

const DEFAULT_TEXT_PADDING: EmailSides = { top: 8, right: 0, bottom: 8, left: 0 }
const NO_PADDING: EmailSides = { top: 0, right: 0, bottom: 0, left: 0 }
const BLOCK_LABELS: Record<string, string> = {
    paragraph: 'Text',
    heading: 'Heading',
    bulletList: 'Bullet list',
    orderedList: 'Numbered list',
    blockquote: 'Quote',
    horizontalRule: 'Divider',
    emailImage: 'Image',
    emailButton: 'Button',
    emailColumns: 'Columns',
    emailSpacer: 'Spacer',
    emailHtml: 'Custom HTML',
}

export function EmailBlockFields({ editor }: { editor: Editor }): JSX.Element | null {
    const { pickImage } = useEmailEditorContext()
    const block = selectedBlock(editor)
    if (!block) {
        return null
    }
    const { node, pos } = block
    const type = node.type.name
    const style = (node.attrs.emailStyle ?? {}) as EmailBlockStyle
    const set = (patch: Partial<EmailBlockStyle>): void => setBlockStyle(editor, pos, patch)
    const page = resolvePageStyle(editor.state.doc.attrs.page)
    const columns = enclosingColumns(editor)

    let fields: JSX.Element | null = null
    switch (type) {
        case 'paragraph':
        case 'heading':
        case 'bulletList':
        case 'orderedList':
        case 'blockquote':
            fields = (
                <>
                    <EmailTextFields editor={editor} nodeType={type} level={node.attrs.level} style={style} set={set} />
                    <EmailBoxFields style={style} set={set} defaultPadding={DEFAULT_TEXT_PADDING} />
                </>
            )
            break
        case 'emailButton':
            fields = (
                <>
                    <EmailFieldRow label="Link">
                        <LemonInput
                            size="small"
                            fullWidth
                            placeholder="https://example.com"
                            value={node.attrs.href}
                            onChange={(href) => setBlockAttribute(editor, pos, 'href', href)}
                            data-attr="email-editor-button-link"
                            status={node.attrs.href ? 'default' : 'danger'}
                        />
                    </EmailFieldRow>
                    {!node.attrs.href ? (
                        <span className="text-xs text-danger">Add a link, or this button won't go anywhere.</span>
                    ) : null}
                    <EmailColorField
                        label="Background"
                        value={style.backgroundColor}
                        placeholder={page.buttonBackgroundColor}
                        onChange={(backgroundColor) => set({ backgroundColor })}
                        attr="email-editor-button-background"
                    />
                    <EmailColorField
                        label="Text"
                        value={style.color}
                        placeholder={page.buttonTextColor}
                        onChange={(color) => set({ color })}
                        attr="email-editor-button-color"
                    />
                    <EmailNumberField
                        label="Font size"
                        value={style.fontSize}
                        placeholder={page.fontSize}
                        min={8}
                        max={40}
                        onChange={(fontSize) => set({ fontSize })}
                    />
                    <EmailNumberField
                        label="Corner radius"
                        value={style.borderRadius}
                        placeholder={page.buttonBorderRadius}
                        onChange={(borderRadius) => set({ borderRadius })}
                        attr="email-editor-button-radius"
                    />
                    <EmailNumberField
                        label="Inner width"
                        value={style.innerPaddingX}
                        placeholder={24}
                        onChange={(innerPaddingX) => set({ innerPaddingX })}
                    />
                    <EmailNumberField
                        label="Inner height"
                        value={style.innerPaddingY}
                        placeholder={12}
                        onChange={(innerPaddingY) => set({ innerPaddingY })}
                    />
                    <EmailNumberField
                        label="Border"
                        value={style.borderWidth}
                        placeholder={0}
                        onChange={(borderWidth) => set({ borderWidth })}
                    />
                    {style.borderWidth ? (
                        <EmailColorField
                            label="Border color"
                            value={style.borderColor}
                            placeholder="#111111"
                            onChange={(borderColor) => set({ borderColor })}
                        />
                    ) : null}
                    <EmailAlignField value={style.textAlign} onChange={(textAlign) => set({ textAlign })} />
                    <EmailBoxFields
                        style={style}
                        set={set}
                        defaultPadding={{ top: 12, right: 0, bottom: 12, left: 0 }}
                        showBackground={false}
                        showBorder={false}
                    />
                </>
            )
            break
        case 'emailImage':
            fields = (
                <>
                    <LemonButton
                        size="small"
                        type="secondary"
                        fullWidth
                        center
                        icon={<IconImage />}
                        data-attr="email-editor-image-replace"
                        onClick={() =>
                            pickImage((image) => {
                                const current = editor.state.doc.nodeAt(pos)
                                if (current) {
                                    editor.view.dispatch(
                                        editor.state.tr.setNodeMarkup(pos, undefined, { ...current.attrs, ...image })
                                    )
                                }
                            })
                        }
                    >
                        {node.attrs.src ? 'Replace image' : 'Choose image'}
                    </LemonButton>
                    <EmailFieldRow label="Alt text">
                        <LemonInput
                            size="small"
                            fullWidth
                            value={node.attrs.alt}
                            placeholder="Describe the image"
                            onChange={(alt) => setBlockAttribute(editor, pos, 'alt', alt)}
                            data-attr="email-editor-image-alt"
                        />
                    </EmailFieldRow>
                    <EmailFieldRow label="Link">
                        <LemonInput
                            size="small"
                            fullWidth
                            value={node.attrs.href}
                            placeholder="https://example.com"
                            onChange={(href) => setBlockAttribute(editor, pos, 'href', href)}
                            data-attr="email-editor-image-link"
                        />
                    </EmailFieldRow>
                    <EmailNumberField
                        label="Width"
                        value={style.width}
                        placeholder={node.attrs.naturalWidth ?? 'Full'}
                        onChange={(width) => set({ width })}
                        attr="email-editor-image-width"
                    />
                    <EmailNumberField
                        label="Corner radius"
                        value={style.borderRadius}
                        placeholder={0}
                        onChange={(borderRadius) => set({ borderRadius })}
                        attr="email-editor-image-radius"
                    />
                    <EmailAlignField value={style.textAlign} onChange={(textAlign) => set({ textAlign })} />
                    <EmailBoxFields
                        style={style}
                        set={set}
                        defaultPadding={NO_PADDING}
                        showBackground={false}
                        showBorder={false}
                    />
                </>
            )
            break
        case 'horizontalRule':
            fields = (
                <>
                    <EmailColorField
                        label="Color"
                        value={style.borderColor}
                        placeholder="#dddddd"
                        onChange={(borderColor) => set({ borderColor })}
                        attr="email-editor-divider-color"
                    />
                    <EmailNumberField
                        label="Thickness"
                        value={style.lineWidth}
                        placeholder={1}
                        min={1}
                        max={20}
                        onChange={(lineWidth) => set({ lineWidth })}
                        attr="email-editor-divider-thickness"
                    />
                    <EmailNumberField
                        label="Length"
                        suffix="%"
                        value={style.width}
                        placeholder={100}
                        min={1}
                        max={100}
                        onChange={(width) => set({ width })}
                    />
                    <EmailBoxFields
                        style={style}
                        set={set}
                        defaultPadding={DEFAULT_TEXT_PADDING}
                        showBackground={false}
                        showBorder={false}
                    />
                </>
            )
            break
        case 'emailSpacer':
            fields = (
                <EmailNumberField
                    label="Height"
                    value={node.attrs.height}
                    min={1}
                    max={400}
                    onChange={(height) => setBlockAttribute(editor, pos, 'height', height ?? 24)}
                    attr="email-editor-spacer-height"
                />
            )
            break
        case 'emailHtml':
            fields = <EmailBoxFields style={style} set={set} defaultPadding={NO_PADDING} showBorder={false} />
            break
        default:
            break
    }

    return (
        <div className="flex flex-col gap-1">
            {type !== 'emailColumns' ? (
                <h3 className="text-sm font-semibold m-0">{BLOCK_LABELS[type] ?? type}</h3>
            ) : null}
            {type !== 'emailColumns' ? fields : null}
            {columns ? (
                <>
                    {type !== 'emailColumns' ? <LemonDivider className="my-1" /> : null}
                    <EmailColumnsFields editor={editor} pos={columns.pos} columnIndex={columns.columnIndex} />
                </>
            ) : null}
        </div>
    )
}
