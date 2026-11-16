import { useActions, useValues } from 'kea'

import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldContent,
    FieldDescription,
    FieldGroup,
    FieldLabel,
    Input,
    RadioGroup,
    RadioGroupItem,
} from '@posthog/quill'

import { MERGE_LIMIT_REASON, MERGE_SOURCE_LIMIT } from './releaseMerge'
import { releaseMergeLogic } from './releaseMergeLogic'
import { ReleaseMergeWarning } from './ReleaseMergeWarning'

export function ReleaseMergeDialog(): JSX.Element {
    const { mergeOpen, mergeTargetId, merging, candidates, keepId, mergeName } = useValues(releaseMergeLogic)
    const { setMergeOpen, setKeepId, editMergeName, mergeReleases } = useActions(releaseMergeLogic)

    const kept = candidates.find((candidate) => candidate.id === keepId)

    return (
        <Dialog open={mergeOpen && !mergeTargetId} onOpenChange={(open: boolean) => setMergeOpen(open)}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>{`Merge ${candidates.length} releases`}</DialogTitle>
                    <DialogDescription>
                        Pick the release to keep. It gets the flags, experiments, surveys, insights and broadcasts of
                        the others, then the others are deleted.
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <FieldGroup>
                        <RadioGroup
                            value={keepId ?? ''}
                            onValueChange={(value) => setKeepId(String(value))}
                            data-attr="release-merge-keep"
                        >
                            {candidates.map((candidate) => (
                                <Field key={candidate.id} orientation="horizontal">
                                    <RadioGroupItem value={candidate.id} id={`release-merge-${candidate.id}`} />
                                    <FieldContent>
                                        <FieldLabel htmlFor={`release-merge-${candidate.id}`}>
                                            {candidate.name}
                                        </FieldLabel>
                                        <FieldDescription>{candidate.summary}</FieldDescription>
                                    </FieldContent>
                                </Field>
                            ))}
                        </RadioGroup>
                        <Field>
                            <FieldLabel htmlFor="release-merge-name">Name</FieldLabel>
                            <Input
                                id="release-merge-name"
                                value={mergeName}
                                onChange={(event) => editMergeName(event.target.value)}
                                data-attr="release-merge-name"
                            />
                        </Field>
                        <ReleaseMergeWarning
                            deleted={candidates
                                .filter((candidate) => candidate.id !== keepId)
                                .map((candidate) => candidate.name)}
                        />
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
                            !kept
                                ? 'Pick the release to keep'
                                : candidates.length - 1 > MERGE_SOURCE_LIMIT
                                  ? MERGE_LIMIT_REASON
                                  : !mergeName.trim()
                                    ? 'Give the release a name'
                                    : undefined
                        }
                        data-attr="release-merge-confirm"
                        onClick={() => kept && mergeReleases(kept.id)}
                    >
                        Merge releases
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
