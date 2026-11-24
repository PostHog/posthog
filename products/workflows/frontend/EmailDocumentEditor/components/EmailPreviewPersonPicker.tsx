import { useState } from 'react'

import { IconX } from '@posthog/icons'
import { LemonButton, LemonDropdown } from '@posthog/lemon-ui'

import { PreviewPerson } from 'scenes/hog-functions/email-templater/preview/emailPreviewPersonLogic'
import { PersonSearch } from 'scenes/hog-functions/email-templater/preview/PersonSearch'

/** Picks whose properties fill the editor's preview. No one is picked until the viewer chooses. */
export function EmailPreviewPersonPicker({
    person,
    onChange,
}: {
    person: PreviewPerson | null
    onChange: (person: PreviewPerson | null) => void
}): JSX.Element {
    const [open, setOpen] = useState(false)

    return (
        <div className="ph-no-capture flex items-center gap-1 min-w-0">
            <span className="text-xs text-secondary shrink-0">Preview as</span>
            <LemonDropdown
                visible={open}
                onClickOutside={() => setOpen(false)}
                closeOnClickInside={false}
                overlay={
                    <div className="ph-no-capture p-1 w-64">
                        <PersonSearch
                            onPick={(picked) => {
                                onChange(picked)
                                setOpen(false)
                            }}
                        />
                    </div>
                }
            >
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    onClick={() => setOpen(!open)}
                    className="min-w-0 max-w-60"
                    data-attr="email-editor-preview-person"
                >
                    <span className="truncate">{person?.displayName ?? 'No one'}</span>
                </LemonButton>
            </LemonDropdown>
            {person ? (
                <LemonButton
                    size="xsmall"
                    icon={<IconX />}
                    tooltip="Preview as no one"
                    onClick={() => onChange(null)}
                    data-attr="email-editor-preview-person-clear"
                />
            ) : null}
        </div>
    )
}
