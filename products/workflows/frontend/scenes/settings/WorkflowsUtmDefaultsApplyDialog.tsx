import { useActions, useValues } from 'kea'

import { LemonButton, LemonCheckbox, LemonModal, Spinner } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { pluralize } from 'lib/utils/strings'

import { QuillWorkflowsUtmDefaultsApplyDialog } from './QuillWorkflowsUtmDefaultsApplyDialog'
import {
    applyUtmDefaultsButtonLabel,
    applyUtmDefaultsDisabledReason,
    utmDefaultsPreviewSummary,
} from './utmDefaultsApplyPreview'
import { workflowsUtmDefaultsApplyLogic } from './workflowsUtmDefaultsApplyLogic'

export function WorkflowsUtmDefaultsApplyDialog(): JSX.Element {
    const { isApplyDialogOpen, enableWhereOff, preview, previewLoading, isPreviewCurrent, applyResultLoading } =
        useValues(workflowsUtmDefaultsApplyLogic)
    const { closeApplyDialog, setEnableWhereOff, applyDefaults } = useActions(workflowsUtmDefaultsApplyLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const applyState = { preview, previewLoading, isPreviewCurrent }

    if (todayRailNav) {
        return <QuillWorkflowsUtmDefaultsApplyDialog />
    }

    return (
        <LemonModal
            isOpen={isApplyDialogOpen}
            onClose={closeApplyDialog}
            title="Update existing emails?"
            description="Existing broadcasts and workflow emails keep their current values until you apply the new defaults. Values typed into a single email stay as they are, and sent broadcasts never change."
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeApplyDialog} data-attr="workflows-utm-defaults-skip">
                        Not now
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={applyDefaults}
                        loading={applyResultLoading}
                        disabledReason={applyUtmDefaultsDisabledReason(applyState)}
                        data-attr="workflows-utm-defaults-apply"
                    >
                        {applyUtmDefaultsButtonLabel(applyState)}
                    </LemonButton>
                </>
            }
        >
            {previewLoading ? (
                <Spinner />
            ) : !preview || !isPreviewCurrent ? (
                <p className="m-0">Couldn't count the emails to update. Close this and try again.</p>
            ) : (
                <div className="flex flex-col gap-3">
                    <p className="m-0">{utmDefaultsPreviewSummary(preview)}</p>
                    {preview.workflows_without_access > 0 && (
                        <p className="m-0 text-secondary">
                            {preview.workflows_without_access} more workflows have emails to update, but you don't have
                            edit access to them. They keep their current values.
                        </p>
                    )}
                    {preview.emails_off > 0 && (
                        <LemonCheckbox
                            checked={enableWhereOff}
                            onChange={setEnableWhereOff}
                            label={`Also turn on UTM tags in ${pluralize(preview.emails_off, 'email')} where they're off`}
                            data-attr="workflows-utm-defaults-enable-where-off"
                        />
                    )}
                </div>
            )}
        </LemonModal>
    )
}
