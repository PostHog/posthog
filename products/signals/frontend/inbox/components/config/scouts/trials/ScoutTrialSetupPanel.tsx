import { useActions, useValues } from 'kea'
import { useState } from 'react'

import type { SignalScoutConfigApi } from 'products/signals/frontend/generated/api.schemas'

import { scoutRubricsLogic } from '../../../../logics/scoutRubricsLogic'
import { scoutDisplayName } from '../../../../utils/scoutRunsWindow'
import { ScoutRubricsModal } from '../ScoutRubricsModal'
import { ScoutTrialSetup, ScoutTrialSetupProps } from './ScoutTrialSetup'

type ScoutTrialSetupPanelProps = Omit<
    ScoutTrialSetupProps,
    'rubric' | 'rubricLoading' | 'rubricError' | 'onViewRubric' | 'onReloadRubric'
> & { teamId: number; config: SignalScoutConfigApi }

export function ScoutTrialSetupPanel(props: ScoutTrialSetupPanelProps): JSX.Element {
    const logic = scoutRubricsLogic({ teamId: props.teamId, configId: props.config.id })
    const { rubricDocument, rubricDocumentLoading, loadError } = useValues(logic)
    const { loadRubrics } = useActions(logic)
    const [showRubric, setShowRubric] = useState(false)

    return (
        <>
            <ScoutTrialSetup
                {...props}
                rubric={rubricDocument}
                rubricLoading={rubricDocumentLoading}
                rubricError={loadError}
                onViewRubric={() => setShowRubric(true)}
                onReloadRubric={loadRubrics}
            />
            {showRubric && (
                <ScoutRubricsModal
                    teamId={props.teamId}
                    configId={props.config.id}
                    scoutName={scoutDisplayName(props.config)}
                    onClose={() => {
                        setShowRubric(false)
                        loadRubrics()
                    }}
                />
            )}
        </>
    )
}
