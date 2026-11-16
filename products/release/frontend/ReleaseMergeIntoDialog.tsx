import { useActions, useValues } from 'kea'
import { useState } from 'react'

import {
    Button,
    Combobox,
    ComboboxChip,
    ComboboxChips,
    ComboboxChipsInput,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxItem,
    ComboboxList,
    ComboboxValue,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldDescription,
    FieldGroup,
    FieldLabel,
    Input,
    useComboboxAnchor,
} from '@posthog/quill'

import { MERGE_LIMIT_REASON, MERGE_SOURCE_LIMIT } from './releaseMerge'
import { releaseMergeLogic } from './releaseMergeLogic'
import { ReleaseMergeWarning } from './ReleaseMergeWarning'

const SEARCH_LIMIT = 20

function ReleaseMergeSourcesInput({ names }: { names: Map<string, string> }): JSX.Element {
    const anchor = useComboboxAnchor()
    return (
        <>
            <ComboboxChips ref={anchor}>
                <ComboboxValue>
                    {(values: string[]) => (
                        <>
                            {values.map((releaseId) => (
                                <ComboboxChip key={releaseId}>{names.get(releaseId)}</ComboboxChip>
                            ))}
                            <ComboboxChipsInput
                                placeholder={values.length ? undefined : 'Search releases'}
                                aria-label="Releases to merge"
                                data-attr="release-merge-into-search"
                            />
                        </>
                    )}
                </ComboboxValue>
            </ComboboxChips>
            <ComboboxContent anchor={anchor}>
                <ComboboxEmpty>No release matches that name.</ComboboxEmpty>
                <ComboboxList>
                    {(releaseId: string) => (
                        <ComboboxItem key={releaseId} value={releaseId} data-attr="release-merge-into-option">
                            <span>{names.get(releaseId)}</span>
                        </ComboboxItem>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </>
    )
}

export function ReleaseMergeIntoDialog(): JSX.Element {
    const { mergeOpen, mergeTargetId, merging, candidates, mergeName, rows, hiddenReleaseIds } =
        useValues(releaseMergeLogic)
    const { setMergeOpen, setMergeSources, editMergeName, mergeReleases } = useActions(releaseMergeLogic)
    const [query, setQuery] = useState('')

    const target = rows.find((row) => row.id === mergeTargetId)
    const sources = candidates.filter((candidate) => candidate.id !== mergeTargetId)
    const options = rows.filter((row) => row.id !== mergeTargetId && !hiddenReleaseIds.has(row.id))
    const names = new Map(options.map((row) => [row.id, row.name]))
    const search = query.trim().toLowerCase()
    const matches = options
        .filter((row) => !search || row.name.toLowerCase().includes(search))
        .slice(0, SEARCH_LIMIT)
        .map((row) => row.id)

    return (
        <Dialog open={mergeOpen && !!mergeTargetId} onOpenChange={(open: boolean) => setMergeOpen(open)}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>Merge releases into this one</DialogTitle>
                    <DialogDescription>
                        {`${target?.name ?? 'This release'} gets the flags, experiments, surveys, insights and broadcasts of the releases you pick.`}
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <FieldGroup>
                        <Field>
                            <FieldLabel>Releases to merge</FieldLabel>
                            <Combobox
                                multiple
                                items={matches}
                                filter={null}
                                value={sources.map((source) => source.id)}
                                onValueChange={(releaseIds: string[]) => setMergeSources(releaseIds)}
                                onInputValueChange={setQuery}
                                itemToStringLabel={(releaseId: string) => names.get(releaseId) ?? ''}
                            >
                                <ReleaseMergeSourcesInput names={names} />
                            </Combobox>
                            {sources.map((source) => (
                                <FieldDescription
                                    key={source.id}
                                >{`${source.name}: ${source.summary}`}</FieldDescription>
                            ))}
                        </Field>
                        <Field>
                            <FieldLabel htmlFor="release-merge-into-name">Name</FieldLabel>
                            <Input
                                id="release-merge-into-name"
                                value={mergeName}
                                onChange={(event) => editMergeName(event.target.value)}
                                data-attr="release-merge-into-name"
                            />
                        </Field>
                        {sources.length > 0 && <ReleaseMergeWarning deleted={sources.map((source) => source.name)} />}
                    </FieldGroup>
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={() => setMergeOpen(false)}>
                        Cancel
                    </Button>
                    <Button
                        variant="destructive"
                        loading={merging}
                        disabledReason={
                            !sources.length
                                ? 'Pick at least one release to merge'
                                : sources.length > MERGE_SOURCE_LIMIT
                                  ? MERGE_LIMIT_REASON
                                  : !mergeName.trim()
                                    ? 'Give the release a name'
                                    : undefined
                        }
                        data-attr="release-merge-into-confirm"
                        onClick={() => mergeTargetId && mergeReleases(mergeTargetId)}
                    >
                        {sources.length > 1 ? `Merge ${sources.length} releases` : 'Merge release'}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
