import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconGear } from '@posthog/icons'
import { LemonButton, type LemonButtonProps, LemonModal, Tooltip } from '@posthog/lemon-ui'

import type { SignalScoutConfigApi as SignalScoutConfig } from 'products/signals/frontend/generated/api.schemas'

import { captureScoutAction } from '../../../inboxAnalytics'
import type { ScoutSurface } from '../../../inboxAnalytics'
import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import { prettifyScoutSkillName } from '../../../utils/scoutRunsWindow'
import { ScoutConfigForm } from './ScoutConfigControls'

/**
 * A scout's configuration, in a modal. It used to expand inline, which pushed whatever you were
 * reading off the screen on the scout page and reflowed the whole table on the roster — and the form
 * is long enough (schedule, network, model, tags, destination, delete) that neither host had room
 * for it. Both surfaces open the same one.
 */
export function ScoutSettingsModal({
    config,
    surface,
    isOpen,
    onClose,
}: {
    config: SignalScoutConfig
    surface: ScoutSurface
    isOpen: boolean
    onClose: () => void
}): JSX.Element {
    const { updatingScoutIds, deletingScoutIds } = useValues(scoutFleetLogic)
    const { updateScoutConfig, deleteScout } = useActions(scoutFleetLogic)

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title={`${prettifyScoutSkillName(config.skill_name)} settings`}
            description="Changes take effect on this scout's next run."
            width={560}
        >
            <ScoutConfigForm
                config={config}
                onUpdate={updateScoutConfig}
                onDelete={(configId) => deleteScout(configId, surface)}
                deleting={deletingScoutIds.includes(config.id)}
                updating={updatingScoutIds.includes(config.id)}
            />
        </LemonModal>
    )
}

/** The gear that opens {@link ScoutSettingsModal}, owning the open state so hosts don't each repeat it. */
export function ScoutSettingsButton({
    config,
    surface,
    size = 'small',
    showLabel = false,
}: {
    config: SignalScoutConfig
    surface: ScoutSurface
    size?: LemonButtonProps['size']
    showLabel?: boolean
}): JSX.Element {
    const [isOpen, setIsOpen] = useState(false)

    return (
        <>
            <Tooltip title={showLabel ? undefined : 'Scout settings'}>
                <LemonButton
                    type={showLabel ? 'secondary' : undefined}
                    size={size}
                    icon={<IconGear />}
                    onClick={() => {
                        captureScoutAction({
                            actionType: 'open_settings',
                            surface,
                            skillName: config.skill_name,
                        })
                        setIsOpen(true)
                    }}
                    aria-label={`${config.skill_name} settings`}
                >
                    {showLabel ? 'Settings' : null}
                </LemonButton>
            </Tooltip>
            {isOpen && <ScoutSettingsModal config={config} surface={surface} isOpen onClose={() => setIsOpen(false)} />}
        </>
    )
}
