// PROTOTYPE, never merged: PostHog/michaelr-context#421. Naming a view: the same prompt as Customer Analytics' saved
// views, plus a line on what the view keeps.
import { useEffect, useState } from 'react'

import { IconGlobe, IconUser } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonSegmentedButton } from '@posthog/lemon-ui'

import { SavedView, ViewQuery, describeQuery } from './viewsPrototypeStore'

export function SaveViewModal({
    isOpen,
    query,
    editing,
    title,
    onClose,
    onSave,
}: {
    isOpen: boolean
    query: ViewQuery
    editing?: SavedView | null
    title?: string
    onClose: () => void
    onSave: (name: string, visibility: SavedView['visibility']) => void
}): JSX.Element {
    const [name, setName] = useState('')
    const [visibility, setVisibility] = useState<SavedView['visibility']>('private')

    useEffect(() => {
        if (isOpen) {
            setName(editing?.name ?? '')
            setVisibility(editing?.visibility ?? 'private')
        }
    }, [isOpen, editing])

    const submit = (): void => {
        if (name.trim()) {
            onSave(name.trim(), visibility)
        }
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title={title ?? (editing ? 'Edit view' : 'Save as new view')}
            description={editing ? undefined : 'Keeps the filters, sort and columns you see now.'}
            footer={
                <>
                    <LemonButton type="secondary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submit}
                        disabledReason={!name.trim() ? 'Give the view a name' : undefined}
                        data-attr="messaging-prototype-save-view-submit"
                    >
                        {editing ? 'Save changes' : 'Save view'}
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                <div className="flex flex-col gap-1">
                    <label className="font-semibold">View name</label>
                    <LemonInput
                        placeholder="e.g. Onboarding emails"
                        autoFocus
                        value={name}
                        onChange={setName}
                        onPressEnter={submit}
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <label className="font-semibold">Visibility</label>
                    <LemonSegmentedButton
                        fullWidth
                        value={visibility}
                        onChange={setVisibility}
                        options={[
                            { value: 'private', label: 'Only me', icon: <IconUser /> },
                            { value: 'shared', label: 'Everyone on the team', icon: <IconGlobe /> },
                        ]}
                    />
                </div>
                {!editing && <div className="text-xs text-secondary">{describeQuery(query)}</div>}
            </div>
        </LemonModal>
    )
}
