import { useActions, useValues } from 'kea'

import {
    AlertDialog,
    AlertDialogClose,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    AlertDialogTrigger,
    Button,
} from 'lib/ui/quill'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import type { RelatedIssuesIssue } from '../recommendations/types'
import { impactTabLogic } from './impactTabLogic'

export function ImpactMergeAction({ pair }: { pair: RelatedIssuesIssue }): JSX.Element {
    const { mergeInFlight } = useValues(impactTabLogic)
    const { mergeRelatedIssues } = useActions(impactTabLogic)
    return (
        <AlertDialog>
            <AlertDialogTrigger
                render={
                    <Button
                        variant="outline"
                        size="xs"
                        loading={mergeInFlight}
                        data-attr="error-tracking-impact-merge"
                    />
                }
            >
                Merge
            </AlertDialogTrigger>
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>Merge these issues?</AlertDialogTitle>
                    <AlertDialogDescription>
                        {`"${pair.related.description || pair.related.name}" will be merged into "${pair.description || pair.name}". They share ${humanFriendlyLargeNumber(pair.shared_sessions)} sessions within 5 seconds of each other.`}
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <AlertDialogClose render={<Button variant="outline" />}>Cancel</AlertDialogClose>
                    <AlertDialogClose
                        render={
                            <Button
                                variant="destructive"
                                onClick={() => mergeRelatedIssues(pair.id, pair.related.id)}
                            />
                        }
                    >
                        Merge
                    </AlertDialogClose>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}
