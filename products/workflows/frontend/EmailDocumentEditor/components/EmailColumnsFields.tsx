import type { Editor } from '@tiptap/core'

import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { setBlockStyle, setColumnCount, setColumnRatios } from '../emailCommands'
import { EmailBlockStyle, EmailSides } from '../emailDocument'
import { EmailColorField } from './fields/EmailColorField'
import { EmailFieldRow } from './fields/EmailFieldRow'
import { EmailNumberField } from './fields/EmailNumberField'
import { EmailSectionTitle } from './fields/EmailSectionTitle'
import { EmailSidesField } from './fields/EmailSidesField'

const NO_PADDING: EmailSides = { top: 0, right: 0, bottom: 0, left: 0 }
const COLUMN_RATIO_PRESETS: Record<number, { label: string; ratios: number[] }[]> = {
    2: [
        { label: '1:1', ratios: [1, 1] },
        { label: '1:2', ratios: [1, 2] },
        { label: '2:1', ratios: [2, 1] },
    ],
    3: [
        { label: '1:1:1', ratios: [1, 1, 1] },
        { label: '1:2:1', ratios: [1, 2, 1] },
    ],
}

export function EmailColumnsFields({
    editor,
    pos,
    columnIndex,
}: {
    editor: Editor
    pos: number
    columnIndex: number
}): JSX.Element | null {
    const node = editor.state.doc.nodeAt(pos)
    if (!node) {
        return null
    }
    const style = (node.attrs.emailStyle ?? {}) as EmailBlockStyle
    let columnPos = pos + 1
    for (let index = 0; index < columnIndex; index++) {
        columnPos += node.child(index).nodeSize
    }
    const column = node.maybeChild(columnIndex)
    const columnStyle = (column?.attrs.emailStyle ?? {}) as EmailBlockStyle
    const presets = COLUMN_RATIO_PRESETS[node.childCount]
    return (
        <>
            <EmailSectionTitle>Columns</EmailSectionTitle>
            <EmailFieldRow label="Number">
                <LemonSegmentedButton
                    size="xsmall"
                    fullWidth
                    value={node.childCount}
                    onChange={(count) => setColumnCount(editor, pos, count)}
                    options={[1, 2, 3, 4].map((count) => ({
                        value: count,
                        label: String(count),
                        'data-attr': `email-editor-columns-${count}`,
                    }))}
                />
            </EmailFieldRow>
            {presets ? (
                <EmailFieldRow label="Widths">
                    <LemonSegmentedButton
                        size="xsmall"
                        fullWidth
                        value={node.content.content.map((child) => child.attrs.ratio).join(':')}
                        onChange={(value) => setColumnRatios(editor, pos, String(value).split(':').map(Number))}
                        options={presets.map((preset) => ({
                            value: preset.ratios.join(':'),
                            label: preset.label,
                            'data-attr': `email-editor-columns-ratio-${preset.label}`,
                        }))}
                    />
                </EmailFieldRow>
            ) : null}
            <EmailColorField
                label="Background"
                value={style.backgroundColor}
                placeholder=""
                onChange={(backgroundColor) => setBlockStyle(editor, pos, { backgroundColor })}
                attr="email-editor-columns-background"
            />
            <EmailSidesField
                label="Padding"
                value={style.padding}
                placeholder={NO_PADDING}
                onChange={(padding) => setBlockStyle(editor, pos, { padding })}
                attr="email-editor-columns-padding"
            />
            {column ? (
                <>
                    <EmailColorField
                        label="Column color"
                        value={columnStyle.backgroundColor}
                        placeholder=""
                        onChange={(backgroundColor) => setBlockStyle(editor, columnPos, { backgroundColor })}
                        attr="email-editor-column-background"
                    />
                    <EmailSidesField
                        label="Column padding"
                        value={columnStyle.padding}
                        placeholder={NO_PADDING}
                        onChange={(padding) => setBlockStyle(editor, columnPos, { padding })}
                        attr="email-editor-column-padding"
                    />
                    <EmailNumberField
                        label="Column border"
                        value={columnStyle.borderWidth}
                        placeholder={0}
                        onChange={(borderWidth) => setBlockStyle(editor, columnPos, { borderWidth })}
                        attr="email-editor-column-border"
                    />
                    {columnStyle.borderWidth ? (
                        <EmailColorField
                            label="Border color"
                            value={columnStyle.borderColor}
                            placeholder="#e5e5e5"
                            onChange={(borderColor) => setBlockStyle(editor, columnPos, { borderColor })}
                        />
                    ) : null}
                </>
            ) : null}
        </>
    )
}
