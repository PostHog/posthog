import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import type { ReactNode } from 'react'

import { IconCheck, IconCopy, IconExternal, IconPencil, IconPulse, IconRocket, IconTrash, IconX } from '@posthog/icons'

import { metalyticsLogic } from 'lib/components/Metalytics/metalyticsLogic'
import { useSceneFileActions } from 'lib/components/Scenes/useSceneFileActions'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { interProjectCopyLogic } from 'scenes/resource-transfer/interProjectCopyLogic'
import { urls } from 'scenes/urls'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'
import { EarlyAccessFeatureStage, EarlyAccessFeatureType, SidePanelTab } from '~/types'

import { earlyAccessFeatureLogic } from './earlyAccessFeatureLogic'

const RESOURCE_TYPE = 'early-access-feature'
const EARLY_ACCESS_FEATURES_DOCS_URL = 'https://posthog.com/docs/feature-flags/early-access-feature-management'

const RELEASE_STAGES: { label: string; tooltip: string; stage: EarlyAccessFeatureStage }[] = [
    {
        label: 'Concept',
        tooltip: 'Users can opt in to register interest, but the feature flag will not be enabled for them.',
        stage: EarlyAccessFeatureStage.Concept,
    },
    {
        label: 'Alpha',
        tooltip: 'Early testing. Opted-in users will have the feature flag enabled.',
        stage: EarlyAccessFeatureStage.Alpha,
    },
    {
        label: 'Beta (default)',
        tooltip: 'Wider testing. Opted-in users will have the feature flag enabled.',
        stage: EarlyAccessFeatureStage.Beta,
    },
    {
        label: 'General availability',
        tooltip: 'Feature becomes read-only. All opted-in users retain access.',
        stage: EarlyAccessFeatureStage.GeneralAvailability,
    },
]

interface EarlyAccessFeatureSceneMenuBarProps {
    isNewEarlyAccessFeature: boolean
    canShowSaveButtons: boolean
    earlyAccessFeatureId: string | null
    accessControlDisabledReason: string | null
    metadata: ReactNode
    onCancel: () => void
}

export function EarlyAccessFeatureSceneMenuBar(props: EarlyAccessFeatureSceneMenuBarProps): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]) {
        return null
    }
    return <EarlyAccessFeatureSceneMenuBarInner {...props} />
}

function EarlyAccessFeatureSceneMenuBarInner({
    isNewEarlyAccessFeature,
    canShowSaveButtons,
    earlyAccessFeatureId,
    accessControlDisabledReason,
    metadata,
    onCancel,
}: EarlyAccessFeatureSceneMenuBarProps): JSX.Element {
    const { earlyAccessFeature, isEarlyAccessFeatureSubmitting, saveDisabledReason } =
        useValues(earlyAccessFeatureLogic)
    const { editFeature, updateStage, deleteEarlyAccessFeature, submitEarlyAccessFeature } =
        useActions(earlyAccessFeatureLogic)
    const { canCopyToProject } = useValues(interProjectCopyLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { instanceId: metalyticsInstanceId } = useValues(metalyticsLogic)
    const showMetalytics = metalyticsInstanceId != null && !!featureFlags[FEATURE_FLAGS.METALYTICS]
    const fileActions = useSceneFileActions(RESOURCE_TYPE, { section: 'project' })

    const accessReason = accessControlDisabledReason ?? undefined
    const confirmDelete = (): void => {
        LemonDialog.open({
            title: 'Permanently delete feature?',
            description: 'Doing so will remove any opt in conditions from the feature flag.',
            primaryButton: {
                children: 'Delete',
                type: 'primary',
                status: 'danger',
                'data-attr': 'confirm-delete-feature',
                onClick: () => {
                    deleteEarlyAccessFeature((earlyAccessFeature as EarlyAccessFeatureType)?.id)
                },
            },
            secondaryButton: {
                children: 'Close',
                type: 'secondary',
            },
        })
    }

    const actions: SceneAction[] = [
        ...(!isNewEarlyAccessFeature ? fileActions : []),
        ...(!isNewEarlyAccessFeature && canCopyToProject && earlyAccessFeatureId
            ? ([
                  {
                      group: 'file',
                      section: 'project',
                      id: `${RESOURCE_TYPE}-menubar-copy-to-project`,
                      label: 'Copy to another project',
                      icon: <IconCopy />,
                      onSelect: () =>
                          router.actions.push(urls.resourceTransfer('EarlyAccessFeature', earlyAccessFeatureId)),
                  },
              ] satisfies SceneAction[])
            : []),
        ...(!isNewEarlyAccessFeature
            ? ([
                  {
                      group: 'file',
                      section: 'delete',
                      id: `${RESOURCE_TYPE}-menubar-delete`,
                      label: 'Delete',
                      icon: <IconTrash />,
                      destructive: true,
                      disabledReason: accessReason,
                      onSelect: confirmDelete,
                  },
              ] satisfies SceneAction[])
            : []),
        ...(canShowSaveButtons
            ? ([
                  {
                      group: 'edit',
                      section: 'save',
                      id: `${RESOURCE_TYPE}-menubar-save`,
                      label: isNewEarlyAccessFeature ? 'Save as draft' : 'Save',
                      icon: <IconCheck />,
                      disabledReason:
                          accessReason ??
                          saveDisabledReason ??
                          (isEarlyAccessFeatureSubmitting ? 'Saving…' : undefined),
                      onSelect: submitEarlyAccessFeature,
                      pinned: { order: 2, variant: 'primary', dataAttr: 'save-feature' },
                  },
                  {
                      group: 'edit',
                      section: 'save',
                      id: `${RESOURCE_TYPE}-menubar-cancel`,
                      label: 'Cancel',
                      icon: <IconX />,
                      disabledReason: isEarlyAccessFeatureSubmitting ? 'Saving…' : undefined,
                      onSelect: onCancel,
                      pinned: { order: 1, variant: 'secondary', dataAttr: 'cancel-feature' },
                  },
              ] satisfies SceneAction[])
            : []),
        ...(!canShowSaveButtons && earlyAccessFeature.stage === EarlyAccessFeatureStage.Draft
            ? ([
                  {
                      group: 'edit',
                      section: 'stage',
                      type: 'submenu',
                      id: `${RESOURCE_TYPE}-menubar-release`,
                      label: 'Release',
                      icon: <IconRocket />,
                      tooltip: 'Publish this feature to make it available',
                      disabledReason: accessReason,
                      items: RELEASE_STAGES.map(({ label, tooltip, stage }) => ({
                          id: `${RESOURCE_TYPE}-menubar-release-${stage}`,
                          label,
                          tooltip,
                          onSelect: () => updateStage(stage),
                      })),
                      pinned: { order: 2, variant: 'primary' },
                  },
              ] satisfies SceneAction[])
            : []),
        ...(!canShowSaveButtons && earlyAccessFeature.stage !== EarlyAccessFeatureStage.GeneralAvailability
            ? ([
                  {
                      group: 'edit',
                      section: 'stage',
                      id: `${RESOURCE_TYPE}-menubar-edit-feature`,
                      label: 'Edit',
                      icon: <IconPencil />,
                      disabledReason: accessReason,
                      onSelect: () => editFeature(true),
                      pinned: { order: 3, variant: 'secondary', dataAttr: 'edit-feature' },
                  },
              ] satisfies SceneAction[])
            : []),
        ...(showMetalytics
            ? ([
                  {
                      group: 'view',
                      id: `${RESOURCE_TYPE}-menubar-metalytics`,
                      label: 'View metalytics',
                      icon: <IconPulse />,
                      opensFloatingUi: true,
                      onSelect: () => openSidePanel(SidePanelTab.Activity, 'metalytics'),
                  },
              ] satisfies SceneAction[])
            : []),
        {
            group: 'view',
            id: `${RESOURCE_TYPE}-menubar-docs`,
            label: 'Early access features docs',
            icon: <IconExternal />,
            onSelect: () => window.open(EARLY_ACCESS_FEATURES_DOCS_URL, '_blank', 'noopener'),
        },
        ...(!isNewEarlyAccessFeature
            ? ([
                  {
                      group: 'metadata',
                      type: 'panel',
                      id: `${RESOURCE_TYPE}-menubar-metadata`,
                      label: 'Metadata',
                      render: () => <>{metadata}</>,
                  },
              ] satisfies SceneAction[])
            : []),
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
