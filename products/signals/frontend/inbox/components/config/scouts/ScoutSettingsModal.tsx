import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconGear } from '@posthog/icons'
import { LemonButton, type LemonButtonProps, LemonModal, Tooltip } from '@posthog/lemon-ui'

import type { SignalScoutConfigApi as SignalScoutConfig } from 'products/signals/frontend/generated/api.schemas'

import type { ScoutSurface } from '../../../inboxAnalytics'
import { scoutDetailActionsLogic } from '../../../logics/scoutDetailActionsLogic'
import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import { scoutDisplayName } from '../../../utils/scoutRunsWindow'
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
    const [hasUnsavedInput, setHasUnsavedInput] = useState(false)

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title={`${scoutDisplayName(config)} settings`}
            description="Changes take effect on this scout's next run."
            width={560}
            hasUnsavedInput={hasUnsavedInput}
        >
            <ScoutConfigForm
                config={config}
                onUpdate={updateScoutConfig}
                onDelete={(configId) => deleteScout(configId, surface)}
                deleting={deletingScoutIds.includes(config.id)}
                updating={updatingScoutIds.includes(config.id)}
                onUnsavedChange={setHasUnsavedInput}
                surface={surface}
            />
        </LemonModal>
    )
}

export function ScoutSettingsButton({
    config,
    size = 'small',
    showLabel = false,
}: {
    config: SignalScoutConfig
    size?: LemonButtonProps['size']
    showLabel?: boolean
}): JSX.Element {
    const { openDialog } = useActions(scoutDetailActionsLogic({ skillName: config.skill_name }))

    return (
        <Tooltip title={showLabel ? undefined : 'Scout settings'}>
            <LemonButton
                type={showLabel ? 'secondary' : undefined}
                size={size}
                icon={<IconGear />}
                onClick={() => openDialog('settings')}
                aria-label={`${scoutDisplayName(config)} settings`}
            >
                {showLabel ? 'Settings' : null}
            </LemonButton>
        </Tooltip>
    )
}
