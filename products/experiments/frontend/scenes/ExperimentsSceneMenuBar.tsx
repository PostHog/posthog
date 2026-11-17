import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import posthog, { DisplaySurveyType } from 'posthog-js'

import { IconInfo, IconMessage, IconPlusSmall } from '@posthog/icons'

import { FeedbackSurveyButton } from 'lib/components/FeedbackSurveyButton/FeedbackSurveyButton'
import { RenderKeybind } from 'lib/components/Shortcuts/RenderKeybind'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { urls } from 'scenes/urls'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'
import { AccessControlLevel, AccessControlResourceType, ExperimentsTabs } from '~/types'

import { experimentsLogic } from 'products/experiments/frontend/scenes/experimentsLogic'
import { SetupInspectorButton } from 'products/experiments/frontend/setupInspector/SetupInspectorButton'
import { setupInspectorLogic } from 'products/experiments/frontend/setupInspector/setupInspectorLogic'

import { NewExperimentButton } from './NewExperimentButton'

const RESOURCE_TYPE = 'experiments'

export function ExperimentsSceneMenuBar({ feedbackSurveyId }: { feedbackSurveyId: string }): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <ExperimentsSceneMenuBarInner feedbackSurveyId={feedbackSurveyId} /> : null
}

function ExperimentsSceneMenuBarInner({ feedbackSurveyId }: { feedbackSurveyId: string }): JSX.Element {
    const { tab } = useValues(experimentsLogic)
    const { canInspect } = useValues(setupInspectorLogic)
    const { openSetupInspector } = useActions(setupInspectorLogic)
    const canCreate = tab !== ExperimentsTabs.SharedMetrics && tab !== ExperimentsTabs.Holdouts

    const actions: SceneAction[] = [
        ...(canCreate
            ? ([
                  {
                      group: 'file',
                      section: 'create',
                      id: `${RESOURCE_TYPE}-menubar-new-experiment`,
                      label: 'New experiment',
                      icon: <IconPlusSmall />,
                      disabledReason:
                          getAccessControlDisabledReason(
                              AccessControlResourceType.Experiment,
                              AccessControlLevel.Editor
                          ) ?? undefined,
                      shortcut: <RenderKeybind keybind={[keyBinds.new]} minimal />,
                      onSelect: () => router.actions.push(urls.experiment('new')),
                      pinned: { order: 1, variant: 'primary', render: () => <NewExperimentButton /> },
                  },
              ] satisfies SceneAction[])
            : []),
        ...(canInspect
            ? ([
                  {
                      group: 'view',
                      id: `${RESOURCE_TYPE}-menubar-setup-context`,
                      label: 'Setup context',
                      icon: <IconInfo />,
                      opensFloatingUi: true,
                      tooltip: 'See what an agent reads about this project before it creates an experiment.',
                      onSelect: openSetupInspector,
                      // The button also hosts the inspector drawer, so it keeps its own control.
                      pinned: { order: 1, variant: 'secondary', render: () => <SetupInspectorButton /> },
                  },
              ] satisfies SceneAction[])
            : []),
        {
            group: 'view',
            id: `${RESOURCE_TYPE}-menubar-feedback`,
            label: 'Feedback',
            icon: <IconMessage />,
            opensFloatingUi: true,
            tooltip: 'Have any questions or feedback?',
            onSelect: () =>
                posthog.displaySurvey(feedbackSurveyId, {
                    displayType: DisplaySurveyType.Popover,
                    ignoreConditions: true,
                    ignoreDelay: true,
                }),
            pinned: {
                order: 2,
                variant: 'secondary',
                render: () => (
                    <FeedbackSurveyButton surveyId={feedbackSurveyId} data-attr="experiments-feedback-button" />
                ),
            },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
