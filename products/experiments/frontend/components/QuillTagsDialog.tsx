import { useEffect, useId, useState } from 'react'

import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    toast,
} from '@posthog/quill'

import { TagsCombobox } from 'lib/components/Scenes/TagsCombobox'
import { useTagPages } from 'lib/components/useTagPages'

/** The "Manage tags" dialog of the analytics list, for one experiment. The caller decides how the tags are saved. */
export function QuillTagsDialog({
    open,
    name,
    tags,
    onSave,
    onClose,
}: {
    open: boolean
    name: string
    tags: string[]
    onSave: (tags: string[]) => Promise<void> | void
    onClose: () => void
}): JSX.Element {
    const [draftTags, setDraftTags] = useState<string[]>(tags)
    const [saving, setSaving] = useState(false)
    const tagPages = useTagPages(useId())

    useEffect(() => {
        if (open) {
            setDraftTags(tags)
        }
    }, [open, tags])

    const hasChanges = draftTags.length !== tags.length || draftTags.some((tag) => !tags.includes(tag))

    const save = async (): Promise<void> => {
        setSaving(true)
        try {
            await onSave(draftTags)
        } catch {
            toast.error({ title: "Couldn't save the tags. Try again." })
        } finally {
            setSaving(false)
        }
    }

    return (
        <Dialog open={open} onOpenChange={(next: boolean) => !next && !saving && onClose()}>
            <DialogContent data-attr="experiments-tags-dialog">
                <DialogHeader>
                    <DialogTitle>Manage tags</DialogTitle>
                    <DialogDescription>{`Tags on "${name}".`}</DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <TagsCombobox
                        value={draftTags}
                        onChange={setDraftTags}
                        options={tagPages.tags.map(({ tag }) => tag).filter((tag) => !draftTags.includes(tag))}
                        loading={tagPages.awaitingFirstPage || tagPages.pageLoading}
                        onOpen={() => tagPages.setOpen(true)}
                        onClose={() => tagPages.setOpen(false)}
                        onInputChange={tagPages.setSearch}
                        error={tagPages.error ? "Couldn't load tags." : undefined}
                        onRetry={tagPages.retry}
                        onScrollEnd={tagPages.loadMore}
                        loadingMore={tagPages.pageLoading && tagPages.tags.length > 0}
                        placeholder="Add tags..."
                        allowCustomValues
                        customValueNoun="tag"
                        autoFocus
                        disabled={saving}
                        dataAttr="experiments-tags-input"
                    />
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={onClose} disabled={saving}>
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        onClick={() => void save()}
                        loading={saving}
                        disabled={!hasChanges}
                        data-attr="experiments-tags-save"
                    >
                        Save
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
