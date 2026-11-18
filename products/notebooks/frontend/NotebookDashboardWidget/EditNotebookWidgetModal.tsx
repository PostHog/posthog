import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { EditWidgetModalTileDetailsSection } from 'products/dashboards/frontend/widgets/EditWidgetModalTileDetailsSection'
import type { DashboardWidgetEditModalProps } from 'products/dashboards/frontend/widgets/registry'

import { editNotebookWidgetLogic } from './editNotebookWidgetLogic'

export function EditNotebookWidgetModal(props: DashboardWidgetEditModalProps): JSX.Element | null {
    return props.isOpen ? <EditNotebookWidgetModalContent {...props} /> : null
}

function EditNotebookWidgetModalContent(props: DashboardWidgetEditModalProps): JSX.Element {
    const { tileName, tileDescription, saving, error } = useValues(editNotebookWidgetLogic(props))
    const { setTileName, setTileDescription, submit } = useActions(editNotebookWidgetLogic(props))
    return (
        <LemonModal
            isOpen
            title="Widget settings"
            onClose={saving ? undefined : props.onClose}
            width={560}
            footer={
                <>
                    <LemonButton onClick={props.onClose} disabledReason={saving ? 'Saving…' : undefined}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" loading={saving} onClick={submit}>
                        Save
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                <EditWidgetModalTileDetailsSection
                    tileName={tileName}
                    tileDescription={tileDescription}
                    defaultTitle={props.defaultTitle ?? 'Notebook widget'}
                    saving={saving}
                    setTileName={setTileName}
                    setTileDescription={setTileDescription}
                />
                <p className="mb-0 text-secondary">
                    This tile keeps a saved widget version and its results. To change its code or inputs, edit the
                    notebook and add the widget again.
                </p>
                {typeof props.config.notebookShortId === 'string' ? (
                    <LemonButton to={urls.notebook(props.config.notebookShortId)}>Open notebook</LemonButton>
                ) : null}
                {error ? <LemonBanner type="error">{error}</LemonBanner> : null}
            </div>
        </LemonModal>
    )
}
