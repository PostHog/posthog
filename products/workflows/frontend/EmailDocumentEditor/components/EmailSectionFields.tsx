import type { Editor } from '@tiptap/core'

import { setBlockStyle } from '../emailCommands'
import { EmailBlockStyle, SECTION_PADDING } from '../emailDocument'
import { EmailColorField } from './fields/EmailColorField'
import { EmailNumberField } from './fields/EmailNumberField'
import { EmailSectionTitle } from './fields/EmailSectionTitle'
import { EmailSidesField } from './fields/EmailSidesField'
import { NUMBER_LIMITS } from './fields/numberLimits'

export function EmailSectionFields({ editor, pos }: { editor: Editor; pos: number }): JSX.Element | null {
    const node = editor.state.doc.nodeAt(pos)
    if (!node) {
        return null
    }
    const style = (node.attrs.emailStyle ?? {}) as EmailBlockStyle
    const set = (patch: Partial<EmailBlockStyle>): void => setBlockStyle(editor, pos, patch)
    return (
        <>
            <EmailSectionTitle>Section</EmailSectionTitle>
            <EmailColorField
                label="Background"
                value={style.backgroundColor}
                placeholder=""
                onChange={(backgroundColor) => set({ backgroundColor })}
                attr="email-editor-section-background"
            />
            <EmailSidesField
                key={`section-padding-${pos}`}
                label="Padding"
                value={style.padding}
                placeholder={SECTION_PADDING}
                onChange={(padding) => set({ padding })}
                attr="email-editor-section-padding"
            />
            <EmailNumberField
                label="Corner radius"
                limit={NUMBER_LIMITS.cornerRadius}
                value={style.borderRadius}
                placeholder={0}
                onChange={(borderRadius) => set({ borderRadius })}
                attr="email-editor-section-radius"
            />
            <EmailNumberField
                label="Border"
                limit={NUMBER_LIMITS.border}
                value={style.borderWidth}
                placeholder={0}
                onChange={(borderWidth) => set({ borderWidth })}
                attr="email-editor-section-border"
            />
            {style.borderWidth ? (
                <EmailColorField
                    label="Border color"
                    value={style.borderColor}
                    placeholder="#e5e5e5"
                    onChange={(borderColor) => set({ borderColor })}
                />
            ) : null}
        </>
    )
}
