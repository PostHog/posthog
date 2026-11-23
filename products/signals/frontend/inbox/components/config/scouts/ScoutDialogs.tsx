import { useActions, useValues } from 'kea'

import { teamLogic } from 'scenes/teamLogic'

import type { SignalScoutConfigApi as SignalScoutConfig } from 'products/signals/frontend/generated/api.schemas'

import { scoutDetailActionsLogic } from '../../../logics/scoutDetailActionsLogic'
import { scoutDisplayName } from '../../../utils/scoutRunsWindow'
import { ScoutRubricsModal } from './ScoutRubricsModal'
import { ScoutSettingsModal } from './ScoutSettingsModal'

/** The dialog a scout control opened. A page renders this once, so every control opens the same dialog. */
export function ScoutDialogs({ config }: { config: SignalScoutConfig }): JSX.Element | null {
    const logic = scoutDetailActionsLogic({ skillName: config.skill_name })
    const { dialog } = useValues(logic)
    const { closeDialog } = useActions(logic)
    const { currentTeamId } = useValues(teamLogic)

    if (dialog === 'settings') {
        return <ScoutSettingsModal config={config} surface="scout_detail" isOpen onClose={closeDialog} />
    }
    if (dialog === 'rubrics' && currentTeamId) {
        return (
            <ScoutRubricsModal
                teamId={currentTeamId}
                configId={config.id}
                scoutName={scoutDisplayName(config)}
                onClose={closeDialog}
            />
        )
    }
    return null
}
