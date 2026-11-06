import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { EmailTextAlign } from '../../emailDocument'
import { EmailFieldRow } from './EmailFieldRow'

export function EmailAlignField({
    value,
    onChange,
}: {
    value: EmailTextAlign | undefined
    onChange: (value: EmailTextAlign) => void
}): JSX.Element {
    return (
        <EmailFieldRow label="Align">
            <LemonSegmentedButton
                size="xsmall"
                fullWidth
                value={value ?? 'left'}
                onChange={onChange}
                options={[
                    { value: 'left', label: 'Left', 'data-attr': 'email-editor-align-left' },
                    { value: 'center', label: 'Center', 'data-attr': 'email-editor-align-center' },
                    { value: 'right', label: 'Right', 'data-attr': 'email-editor-align-right' },
                ]}
            />
        </EmailFieldRow>
    )
}
