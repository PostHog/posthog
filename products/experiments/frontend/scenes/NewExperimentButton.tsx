import { useActions } from 'kea'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import MaxTool from 'scenes/max/MaxTool'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { experimentsLogic } from 'products/experiments/frontend/scenes/experimentsLogic'

export function NewExperimentButton(): JSX.Element {
    const { loadExperiments } = useActions(experimentsLogic)
    const { reportExperimentsListAiBadgeClicked } = useActions(eventUsageLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.Experiment}
            minAccessLevel={AccessControlLevel.Editor}
        >
            <div className="flex items-center gap-2">
                <MaxTool
                    identifier="create_experiment"
                    initialMaxPrompt="Create an experiment for "
                    suggestions={[
                        'Create an experiment to test…',
                        'Set up an A/B test with a 70/30 split between control and test for…',
                    ]}
                    callback={(toolOutput: {
                        experiment_id?: string | number
                        experiment_name?: string
                        feature_flag_key?: string
                        error?: string
                    }) => {
                        if (toolOutput?.error || !toolOutput?.experiment_id) {
                            lemonToast.error(`Failed to create experiment: ${toolOutput?.error || 'Unknown error'}`)
                            return
                        }
                        // Refresh experiments list to show new experiment, then redirect to it
                        loadExperiments()
                        router.actions.push(urls.experiment(toolOutput.experiment_id))
                    }}
                    position="bottom-right"
                    active={true}
                    onMaxOpen={reportExperimentsListAiBadgeClicked}
                    // Recorded as `ai_entry_point` on `experiment created`
                    context={{ entry_point: 'experiments_list' }}
                >
                    <Shortcut
                        name="NewExperiment"
                        keybind={[keyBinds.new]}
                        intent="New experiment"
                        interaction="click"
                        scope={Scene.Experiments}
                    >
                        {todayRailNav ? (
                            <Button
                                variant="primary"
                                data-attr="create-experiment"
                                render={<LinkPrimitive to={urls.experiment('new')} />}
                                tooltip="New experiment"
                            >
                                <span className="pr-3">New experiment</span>
                            </Button>
                        ) : (
                            <LemonButton
                                size="small"
                                type="primary"
                                data-attr="create-experiment"
                                to={urls.experiment('new')}
                                tooltip="New experiment"
                            >
                                <span className="pr-3">New experiment</span>
                            </LemonButton>
                        )}
                    </Shortcut>
                </MaxTool>
            </div>
        </AccessControlAction>
    )
}
