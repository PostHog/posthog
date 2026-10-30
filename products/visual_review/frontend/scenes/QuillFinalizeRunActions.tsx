import { IconInfo } from '@posthog/icons'
import { Button, Checkbox, Label, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

export interface QuillFinalizeRunActionsProps {
    addImagesToComment: boolean
    setAddImagesToComment: (enabled: boolean) => void
    isFinalizing: boolean
    finalizeRun: () => void
    reviewPending: number
}

export function QuillFinalizeRunActions({
    addImagesToComment,
    setAddImagesToComment,
    isFinalizing,
    finalizeRun,
    reviewPending,
}: QuillFinalizeRunActionsProps): JSX.Element {
    return (
        <div className="flex flex-wrap items-center gap-2">
            <div className="flex items-center gap-2">
                <Checkbox
                    id="visual-review-add-images-to-comment"
                    checked={addImagesToComment}
                    onCheckedChange={(checked) => setAddImagesToComment(checked)}
                    disabledReason={isFinalizing ? 'Finalizing…' : undefined}
                    data-attr="visual-review-add-images-to-comment"
                />
                <Label htmlFor="visual-review-add-images-to-comment">Add snapshots to the PR comment</Label>
                <Tooltip>
                    <TooltipTrigger render={<span className="flex text-secondary" />}>
                        <IconInfo className="size-4" />
                    </TooltipTrigger>
                    <TooltipContent>
                        The PR comment is always posted; tick this to attach the before/after snapshot images to it.
                        Remembered for next time.
                    </TooltipContent>
                </Tooltip>
            </div>
            <Button
                variant="primary"
                onClick={finalizeRun}
                loading={isFinalizing}
                data-attr="visual-review-finalize-run"
            >
                {reviewPending > 0 ? `Approve ${reviewPending} and finalize` : 'Finalize run'}
            </Button>
        </div>
    )
}
