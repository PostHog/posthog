import { LemonDivider } from '@posthog/lemon-ui'

import { EmailBlockStyle, EmailSides } from '../emailDocument'
import { EmailColorField } from './fields/EmailColorField'
import { EmailNumberField } from './fields/EmailNumberField'
import { EmailSectionTitle } from './fields/EmailSectionTitle'
import { EmailSidesField } from './fields/EmailSidesField'

export function EmailBoxFields({
    style,
    set,
    defaultPadding,
    showBackground = true,
    showBorder = true,
}: {
    style: EmailBlockStyle
    set: (patch: Partial<EmailBlockStyle>) => void
    defaultPadding: EmailSides
    showBackground?: boolean
    showBorder?: boolean
}): JSX.Element {
    return (
        <>
            <LemonDivider className="my-1" />
            <EmailSectionTitle>Spacing</EmailSectionTitle>
            <EmailSidesField
                label="Padding"
                value={style.padding}
                placeholder={defaultPadding}
                onChange={(padding) => set({ padding })}
                attr="email-editor-block-padding"
            />
            {showBackground ? (
                <EmailColorField
                    label="Background"
                    value={style.backgroundColor}
                    placeholder=""
                    onChange={(backgroundColor) => set({ backgroundColor })}
                    attr="email-editor-block-background"
                />
            ) : null}
            {showBorder ? (
                <>
                    <EmailNumberField
                        label="Corner radius"
                        value={style.borderRadius}
                        placeholder={0}
                        onChange={(borderRadius) => set({ borderRadius })}
                    />
                    <EmailNumberField
                        label="Border"
                        value={style.borderWidth}
                        placeholder={0}
                        onChange={(borderWidth) => set({ borderWidth })}
                        attr="email-editor-block-border"
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
            ) : null}
        </>
    )
}
