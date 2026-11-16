import { useState } from 'react'

import { IconPencil, IconPlus } from '@posthog/icons'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { TagsInputSelect } from 'lib/components/TagsInputSelect'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

interface WorkflowTagsCellProps {
    tags: string[]
    canEdit: boolean
    onChange: (tags: string[]) => void
    onTagClick: (tag: string) => void
}

export function WorkflowTagsCell({ tags, canEdit, onChange, onTagClick }: WorkflowTagsCellProps): JSX.Element | null {
    const [editing, setEditing] = useState(false)

    if (editing) {
        return (
            <TagsInputSelect
                value={tags}
                onChange={onChange}
                onBlur={() => setEditing(false)}
                autoFocus
                size="small"
                className="min-w-48"
                placeholder='try "growth"'
                popoverClassName="click-outside-block"
                data-attr="workflow-list-tags-input"
            />
        )
    }

    if (!tags.length && !canEdit) {
        return null
    }

    return (
        <div className="flex items-center gap-1" data-attr="workflow-list-tags">
            {tags.length > 0 && <ObjectTags tags={tags} staticOnly onTagClick={onTagClick} maxVisibleTags={3} />}
            {canEdit && (
                // Shown on row hover so a long list stays calm. Keyboard focus shows it too.
                <LemonButton
                    size="xsmall"
                    icon={tags.length ? <IconPencil /> : <IconPlus />}
                    tooltip={tags.length ? 'Edit tags' : 'Add tags'}
                    aria-label={tags.length ? 'Edit tags' : 'Add tags'}
                    onClick={() => setEditing(true)}
                    className="opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
                    data-attr="workflow-list-edit-tags"
                />
            )}
        </div>
    )
}
