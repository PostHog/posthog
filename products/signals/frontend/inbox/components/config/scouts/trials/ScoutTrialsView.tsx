import { LemonBanner, LemonInputSelect, LemonSkeleton } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import type { scoutTrialsLogicActions, scoutTrialsLogicValues } from '../../../../logics/scoutTrialsLogic'
import { scoutDisplayName } from '../../../../utils/scoutRunsWindow'
import { ScoutTrialDetail } from './ScoutTrialDetail'
import { ScoutTrialHistory } from './ScoutTrialHistory'
import { ScoutTrialRunDrawer } from './ScoutTrialRunDrawer'
import { ScoutTrialRunHistory } from './ScoutTrialRunHistory'
import { ScoutTrialSetupPanel } from './ScoutTrialSetupPanel'

type ViewAction =
    | 'loadConfigs'
    | 'loadSetup'
    | 'retryPageLoad'
    | 'loadHistory'
    | 'selectConfig'
    | 'updateVariant'
    | 'addVariant'
    | 'removeVariant'
    | 'setRepeats'
    | 'setNote'
    | 'submitComparison'
    | 'newComparison'
    | 'showTrialList'
    | 'refreshResults'
    | 'selectResult'
    | 'downloadResults'
    | 'cancelRun'
    | 'selectComparison'
    | 'loadEvaluation'
    | 'scoreComparison'
    | 'newScoringAttempt'
    | 'downloadEvaluation'
    | 'loadComparison'
    | 'resumeComparison'
    | 'loadComparisonHistory'

export type ScoutTrialsViewProps = scoutTrialsLogicValues & {
    teamId: number
    fixedConfigId?: string
} & {
    [Action in ViewAction]: (...args: Parameters<scoutTrialsLogicActions[Action]>) => void
}

export function ScoutTrialsView(props: ScoutTrialsViewProps): JSX.Element {
    const { configs, configsLoading, selectedConfigId, setup, setupLoading, pageError, submitting } = props
    const currentSetup = setup?.config_id === selectedConfigId ? setup : null
    const selectedConfig = configs?.find((config) => config.id === selectedConfigId)

    return (
        <div className="@container flex flex-1 min-h-0 min-w-0 flex-col overflow-auto ph-no-capture ph-replay-block">
            <div className="mx-auto flex w-full max-w-6xl flex-col gap-5 p-4 @3xl:p-6">
                {!props.fixedConfigId && (
                    <LemonField.Pure label="Scout">
                        <LemonInputSelect
                            mode="single"
                            value={selectedConfigId ? [selectedConfigId] : []}
                            options={(configs ?? []).map((config) => ({
                                key: config.id,
                                label: scoutDisplayName(config),
                            }))}
                            onChange={([configId]) => {
                                if (configId && configId !== selectedConfigId) {
                                    props.selectConfig(configId)
                                }
                            }}
                            placeholder="Search scouts"
                            data-attr="scout-trial-scout-picker"
                            loading={configsLoading}
                            disabledReason={submitting ? 'Wait for the trial to start.' : undefined}
                            fullWidth
                            popoverClassName="ph-no-capture ph-replay-block"
                        />
                    </LemonField.Pure>
                )}
                {props.trialsDisabledReason && (
                    <LemonBanner type="info">
                        New trials and judging are currently disabled. Saved results are still available.
                    </LemonBanner>
                )}
                {pageError && (
                    <LemonBanner
                        type="error"
                        action={{
                            children: 'Retry',
                            onClick: props.retryPageLoad,
                            loading: configsLoading || setupLoading,
                        }}
                    >
                        {pageError}
                    </LemonBanner>
                )}
                {props.pollError && <LemonBanner type="warning">{props.pollError}</LemonBanner>}
                {configsLoading && !configs ? (
                    <LemonSkeleton className="h-64" />
                ) : configs?.length === 0 ? (
                    <LemonBanner type="info">
                        No scouts are available. Add a scout from the Scouts page, then return here.
                    </LemonBanner>
                ) : (
                    selectedConfigId && (
                        <>
                            {props.trialView === 'setup' ? (
                                setupLoading ? (
                                    <LemonSkeleton className="h-64" />
                                ) : currentSetup && selectedConfig ? (
                                    <ScoutTrialSetupPanel
                                        {...props}
                                        setup={currentSetup}
                                        config={selectedConfig}
                                        onBack={props.showTrialList}
                                    />
                                ) : null
                            ) : props.trialView === 'detail' && props.selectedComparison ? (
                                <ScoutTrialDetail {...props} />
                            ) : (
                                <>
                                    <ScoutTrialHistory {...props} />
                                    <ScoutTrialRunHistory {...props} />
                                </>
                            )}
                        </>
                    )
                )}
                <ScoutTrialRunDrawer
                    result={props.selectedResult}
                    launchId={props.selectedLaunchId}
                    error={props.selectedLaunchId ? props.resultErrors[props.selectedLaunchId] : null}
                    report={props.evaluationState.value?.report}
                    onClose={() => props.selectResult(null)}
                />
            </div>
        </div>
    )
}
