import { useActions, useValues } from 'kea'
import { useId } from 'react'

import {
    Button,
    Checkbox,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldLabel,
    Spinner,
    Text,
} from '@posthog/quill'

import { pluralize } from 'lib/utils/strings'

import {
    applyUtmDefaultsButtonLabel,
    applyUtmDefaultsDisabledReason,
    utmDefaultsPreviewSummary,
} from './utmDefaultsApplyPreview'
import { workflowsUtmDefaultsApplyLogic } from './workflowsUtmDefaultsApplyLogic'

export function QuillWorkflowsUtmDefaultsApplyDialog(): JSX.Element {
    const { isApplyDialogOpen, enableWhereOff, preview, previewLoading, isPreviewCurrent, applyResultLoading } =
        useValues(workflowsUtmDefaultsApplyLogic)
    const { closeApplyDialog, setEnableWhereOff, applyDefaults } = useActions(workflowsUtmDefaultsApplyLogic)
    const enableWhereOffId = useId()

    const applyState = { preview, previewLoading, isPreviewCurrent }

    return (
        <Dialog open={isApplyDialogOpen} onOpenChange={(open: boolean) => !open && closeApplyDialog()}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>Update existing emails?</DialogTitle>
                    <DialogDescription>
                        Existing broadcasts and workflow emails keep their current values until you apply the new
                        defaults. Values typed into a single email stay as they are, and sent broadcasts never change.
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    {previewLoading ? (
                        <Spinner />
                    ) : !preview || !isPreviewCurrent ? (
                        <Text size="xs" render={<p className="m-0" />}>
                            Couldn't count the emails to update. Close this and try again.
                        </Text>
                    ) : (
                        <div className="flex flex-col gap-3">
                            <Text size="xs" render={<p className="m-0" />}>
                                {utmDefaultsPreviewSummary(preview)}
                            </Text>
                            {preview.workflows_without_access > 0 && (
                                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                    {`${preview.workflows_without_access} more workflows have emails to update, but you don't have edit access to them. They keep their current values.`}
                                </Text>
                            )}
                            {preview.emails_off > 0 && (
                                <Field orientation="horizontal">
                                    <Checkbox
                                        id={enableWhereOffId}
                                        checked={enableWhereOff}
                                        onCheckedChange={(checked: boolean) => setEnableWhereOff(checked)}
                                        data-attr="workflows-utm-defaults-enable-where-off"
                                    />
                                    <FieldLabel htmlFor={enableWhereOffId}>
                                        {`Also turn on UTM tags in ${pluralize(preview.emails_off, 'email')} where they're off`}
                                    </FieldLabel>
                                </Field>
                            )}
                        </div>
                    )}
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={closeApplyDialog} data-attr="workflows-utm-defaults-skip">
                        Not now
                    </Button>
                    <Button
                        variant="primary"
                        onClick={applyDefaults}
                        loading={applyResultLoading}
                        disabledReason={applyUtmDefaultsDisabledReason(applyState)}
                        data-attr="workflows-utm-defaults-apply"
                    >
                        {applyUtmDefaultsButtonLabel(applyState)}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
