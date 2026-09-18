import { useActions, useValues } from 'kea'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonInput, LemonModal, LemonTag } from '@posthog/lemon-ui'

import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { colorForString } from 'lib/utils/colors'

import { workflowTagsLogic } from './workflowTagsLogic'

export function ManageWorkflowTagsModal(): JSX.Element {
    const {
        isManageTagsModalOpen,
        pinnedTags,
        pinnedTagsLoading,
        matchingTags,
        newTagName,
        normalizedNewTagName,
        newTagExists,
    } = useValues(workflowTagsLogic)
    const { closeManageTagsModal, setNewTagName, createTag, deleteTag } = useActions(workflowTagsLogic)

    const canCreate = normalizedNewTagName.length > 0 && !newTagExists

    const confirmDelete = (tag: (typeof matchingTags)[number]): void => {
        LemonDialog.open({
            title: `Remove the tag "${tag.name}"?`,
            description:
                'The tag is no longer offered when people tag a workflow. Workflows that already have it keep it until you remove it from them.',
            primaryButton: {
                children: 'Remove tag',
                status: 'danger',
                onClick: () => deleteTag(tag),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <LemonModal
            isOpen={isManageTagsModalOpen}
            onClose={closeManageTagsModal}
            title="Manage tags"
            description="Create the tags people can pick from when they tag a workflow. Search first, so one topic does not end up with two tags."
            width={480}
            footer={
                <LemonButton type="secondary" onClick={closeManageTagsModal} data-attr="workflow-tags-modal-close">
                    Done
                </LemonButton>
            }
        >
            <div className="flex flex-col gap-3">
                <div className="flex gap-2">
                    <LemonInput
                        type="search"
                        className="flex-1"
                        placeholder="Search or create a tag"
                        value={newTagName}
                        onChange={setNewTagName}
                        onPressEnter={() => canCreate && !pinnedTagsLoading && createTag(normalizedNewTagName)}
                        autoFocus
                        data-attr="workflow-tags-modal-input"
                    />
                    <LemonButton
                        type="primary"
                        onClick={() => createTag(normalizedNewTagName)}
                        loading={pinnedTagsLoading && normalizedNewTagName.length > 0}
                        disabledReason={
                            normalizedNewTagName.length === 0
                                ? 'Type a tag name first'
                                : newTagExists
                                  ? 'This tag already exists'
                                  : undefined
                        }
                        data-attr="workflow-tags-modal-create"
                    >
                        Create tag
                    </LemonButton>
                </div>
                {normalizedNewTagName.length > 0 && normalizedNewTagName !== newTagName && (
                    <p className="text-secondary text-xs m-0">
                        <span>Saved as&nbsp;</span>
                        <span translate="no">{normalizedNewTagName}</span>
                    </p>
                )}

                {pinnedTags === null ? (
                    <div className="flex flex-col gap-2">
                        <LemonSkeleton className="h-8" />
                        <LemonSkeleton className="h-8" />
                    </div>
                ) : pinnedTags.length === 0 ? (
                    <p className="text-secondary m-0">No tags yet. Type a name above and create the first one.</p>
                ) : matchingTags.length === 0 ? (
                    <p className="text-secondary m-0">No tag matches your search. Create it with the button above.</p>
                ) : (
                    <ul className="flex flex-col divide-y m-0 p-0 list-none max-h-80 overflow-y-auto">
                        {matchingTags.map((tag) => (
                            <li key={tag.id} className="flex items-center justify-between gap-2 py-1">
                                <LemonTag type={colorForString(tag.name)} wrap className="max-w-full">
                                    {tag.name}
                                </LemonTag>
                                <LemonButton
                                    size="small"
                                    status="danger"
                                    icon={<IconTrash />}
                                    tooltip="Remove tag"
                                    onClick={() => confirmDelete(tag)}
                                    data-attr="workflow-tags-modal-remove"
                                />
                            </li>
                        ))}
                    </ul>
                )}
            </div>
        </LemonModal>
    )
}
