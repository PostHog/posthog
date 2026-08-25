import { LemonSwitch } from '@posthog/lemon-ui'

export interface ScoutRunSettingsTogglesProps {
    enabled: boolean
    emit: boolean
    onEnabledChange: (enabled: boolean) => void
    onEmitChange: (emit: boolean) => void
    disabledReason?: string
}

export function ScoutRunSettingsToggles({
    enabled,
    emit,
    onEnabledChange,
    onEmitChange,
    disabledReason,
}: ScoutRunSettingsTogglesProps): JSX.Element {
    return (
        <>
            <LemonSwitch
                checked={enabled}
                onChange={onEnabledChange}
                label="Enable this scout"
                bordered
                fullWidth
                disabledReason={disabledReason}
            />
            <LemonSwitch
                checked={emit}
                onChange={onEmitChange}
                label="Write signals to the inbox"
                bordered
                fullWidth
                disabledReason={disabledReason}
            />
            <span className="text-xs text-muted">Turn off inbox signals to run the scout in dry-run mode.</span>
        </>
    )
}
