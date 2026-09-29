import { useValues } from 'kea'
import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import type { SignalScoutConfigApi } from 'products/signals/frontend/generated/api.schemas'

import { scoutDisplayName } from '../../../utils/scoutRunsWindow'
import { ScoutRubricsModal } from './ScoutRubricsModal'

export function ScoutRubricsButton({ config }: { config: SignalScoutConfigApi }): JSX.Element | null {
    const { currentTeamId } = useValues(teamLogic)
    const { user } = useValues(userLogic)
    const [isOpen, setIsOpen] = useState(false)

    if (currentTeamId !== 2 || !user?.is_staff) {
        return null
    }

    return (
        <>
            <LemonButton type="secondary" size="small" onClick={() => setIsOpen(true)} data-attr="scout-rubrics-open">
                Rubrics
            </LemonButton>
            {isOpen && (
                <ScoutRubricsModal
                    teamId={currentTeamId}
                    configId={config.id}
                    scoutName={scoutDisplayName(config)}
                    onClose={() => setIsOpen(false)}
                />
            )}
        </>
    )
}
