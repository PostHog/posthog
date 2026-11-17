import { IconCheck, IconDownload, IconExternal, IconX } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { appEditorUrl } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import type { QuillHeatmapActionsProps } from './QuillHeatmapActions'

const RESOURCE_TYPE = 'heatmap'

export function HeatmapSceneMenuBar(props: QuillHeatmapActionsProps): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <HeatmapSceneMenuBarInner {...props} /> : null
}

function HeatmapSceneMenuBarInner({
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
    const actions: SceneAction[] = [
        {
            group: 'file',
            id: `${RESOURCE_TYPE}-menubar-export`,
            label: 'Export',
            icon: <IconDownload />,
            tooltip: 'Export heatmap as PNG',
            disabledReason: exportDisabledReason,
            onSelect: onExport,
            pinned: {
                order: 2,
                variant: 'secondary',
                // The scene returns focus to this button after a save, so it keeps its ref.
                render: () => (
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
                ),
            },
        },
        ...(showSaveButtons
            ? ([
                  {
                      group: 'edit',
                      section: 'save',
                      id: `${RESOURCE_TYPE}-menubar-save`,
                      label: 'Save',
                      icon: <IconCheck />,
                      disabledReason: saveDisabledReason ?? undefined,
                      onSelect: onSave,
                      pinned: {
                          order: 1,
                          variant: 'primary',
                          render: () => (
                              <Button
                                  variant="primary"
                                  onClick={onSave}
                                  loading={saving}
                                  disabledReason={saveDisabledReason}
                                  data-attr="heatmap-save"
                              >
                                  {saving ? 'Saving…' : 'Save'}
                              </Button>
                          ),
                      },
                  },
                  {
                      group: 'edit',
                      section: 'save',
                      id: `${RESOURCE_TYPE}-menubar-discard-changes`,
                      label: 'Discard changes',
                      icon: <IconX />,
                      disabledReason: saving ? 'Saving changes' : undefined,
                      onSelect: onDiscard,
                      // pinned: data-attr values are wire strings
                      pinned: { order: 1, variant: 'secondary', dataAttr: 'heatmap-discard-changes' },
                  },
              ] satisfies SceneAction[])
            : []),
        {
            group: 'view',
            id: `${RESOURCE_TYPE}-menubar-open-in-toolbar`,
            label: 'Open in toolbar',
            icon: <IconExternal />,
            tooltip: 'Explore heatmaps on your website, including pages that require a login',
            disabledReason: !displayUrl ? 'Select a URL first' : (openInToolbarDisabledReason ?? undefined),
            onSelect: () => {
                if (displayUrl) {
                    window.open(appEditorUrl(displayUrl, { userIntent: 'heatmaps' }), '_blank')
                }
            },
            pinned: { order: 3, variant: 'secondary', dataAttr: 'heatmaps-open-in-toolbar' },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
