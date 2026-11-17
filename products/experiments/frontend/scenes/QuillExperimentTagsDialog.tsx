import { useValues } from 'kea'
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

import { Experiment } from '~/types'

import { experimentsPartialUpdate } from 'products/experiments/frontend/generated/api'
import { experimentsLogic } from 'products/experiments/frontend/scenes/experimentsLogic'

export function QuillExperimentTagsDialog({
    experiment,
    onClose,
    onSaved,
}: {
    experiment: Experiment | null
    onClose: () => void
    onSaved: () => void
}): JSX.Element {
    const { currentProjectId } = useValues(experimentsLogic)
    const [draftTags, setDraftTags] = useState<string[]>([])
    const [saving, setSaving] = useState(false)
    const tagPages = useTagPages(useId())

    useEffect(() => {
        setDraftTags(experiment?.tags ?? [])
    }, [experiment])

    const savedTags = experiment?.tags ?? []
    const hasChanges = draftTags.length !== savedTags.length || draftTags.some((tag) => !savedTags.includes(tag))

    const save = async (): Promise<void> => {
        if (!experiment || typeof experiment.id !== 'number') {
            return
        }
        setSaving(true)
        try {
            await experimentsPartialUpdate(String(currentProjectId), experiment.id, { tags: draftTags })
            onSaved()
        } catch {
            toast.error({ title: "Couldn't save the tags. Try again." })
        } finally {
            setSaving(false)
        }
    }

    return (
        <Dialog open={!!experiment} onOpenChange={(open: boolean) => !open && !saving && onClose()}>
            <DialogContent data-attr="experiments-tags-dialog">
                <DialogHeader>
                    <DialogTitle>Manage tags</DialogTitle>
                    <DialogDescription>{experiment ? `Tags on "${experiment.name}".` : ''}</DialogDescription>
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
