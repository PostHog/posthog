import { IconInfo } from '@posthog/icons'
import { Button, Checkbox, Label, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import type { FinalizeButtonCopy } from '../lib/reviewDecisions'

export interface QuillFinalizeRunActionsProps {
    addImagesToComment: boolean
    setAddImagesToComment: (enabled: boolean) => void
    isFinalizing: boolean
    finalizeRun: () => void
    button: FinalizeButtonCopy
    /** Set when some changes were accepted by an agent, to filter the strip to them. */
    onShowAgentAccepts?: () => void
}

export function QuillFinalizeRunActions({
    addImagesToComment,
    setAddImagesToComment,
    isFinalizing,
    finalizeRun,
    button,
    onShowAgentAccepts,
}: QuillFinalizeRunActionsProps): JSX.Element {
    return (
        <div className="flex flex-wrap items-center gap-2">
            {button.note && (
                <span className="flex items-center gap-1 text-xs text-secondary">
                    <span data-attr="visual-review-finalize-progress">{button.note}</span>
                    {onShowAgentAccepts && (
                        <Button
                            variant="link"
                            size="xs"
                            onClick={onShowAgentAccepts}
                            data-attr="visual-review-show-agent-accepts"
                        >
                            Show them
                        </Button>
                    )}
                </span>
            )}
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
                tooltip={button.tooltip ?? undefined}
                disabledReason={button.disabledReason ?? undefined}
                data-attr="visual-review-finalize-run"
            >
                {isFinalizing ? 'Finalizing…' : button.label}
            </Button>
        </div>
    )
}
