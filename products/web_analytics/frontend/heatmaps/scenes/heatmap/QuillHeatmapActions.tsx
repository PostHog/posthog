import type { MutableRefObject } from 'react'

import { IconDownload } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { appEditorUrl } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

export interface QuillHeatmapActionsProps {
    showSaveButtons: boolean
    saving: boolean
    saveDisabledReason: string | null | undefined
    onDiscard: () => void
    onSave: () => void
    displayUrl: string | null | undefined
    openInToolbarDisabledReason: string | null | undefined
    exportRef: MutableRefObject<HTMLButtonElement | null>
    onExport: () => void
    exportDisabledReason: string | undefined
}

export function QuillHeatmapActions({
    showSaveButtons,
    saving,
    saveDisabledReason,
    onDiscard,
    onSave,
    displayUrl,
    openInToolbarDisabledReason,
    exportRef,
    onExport,
    exportDisabledReason,
}: QuillHeatmapActionsProps): JSX.Element {
    return (
        <>
            {showSaveButtons && (
                <>
                    <Button
                        variant="outline"
                        onClick={onDiscard}
                        disabledReason={saving ? 'Saving changes' : null}
                        data-attr="heatmap-discard-changes"
                    >
                        Discard changes
                    </Button>
                    <Button
                        variant="primary"
                        onClick={onSave}
                        loading={saving}
                        disabledReason={saveDisabledReason}
                        data-attr="heatmap-save"
                    >
                        {saving ? 'Saving…' : 'Save'}
                    </Button>
                </>
            )}
            <Button
                {...(displayUrl
                    ? {
                          nativeButton: false,
                          render: (
                              <LinkPrimitive
                                  to={appEditorUrl(displayUrl, { userIntent: 'heatmaps' })}
                                  target="_blank"
                              />
                          ),
                      }
                    : {})}
                data-attr="heatmaps-open-in-toolbar"
                disabledReason={!displayUrl ? 'Select a URL first' : openInToolbarDisabledReason}
                tooltip="Explore heatmaps on your website, including pages that require a login"
            >
                Open in toolbar
            </Button>
            <Button
                ref={exportRef}
                onClick={onExport}
                data-attr="export-heatmap"
                variant="outline"
                tooltip="Export heatmap as PNG"
                disabledReason={exportDisabledReason}
            >
                <IconDownload />
                Export
            </Button>
        </>
    )
}
