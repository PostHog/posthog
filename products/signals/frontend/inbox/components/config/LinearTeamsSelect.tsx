import { LemonInputSelect } from '@posthog/lemon-ui'

import { useLinearTeams } from 'lib/integrations/LinearIntegrationHelpers'

export interface LinearTeamsSelectProps {
    integrationId: number
    disabled?: boolean
    value?: string[]
    onChange?: (value: string[]) => void
}

export function LinearTeamsSelect({ integrationId, disabled, value, onChange }: LinearTeamsSelectProps): JSX.Element {
    const { options, loading } = useLinearTeams(integrationId)
    return (
        <LemonInputSelect
            mode="multiple"
            value={value ?? []}
            onChange={onChange}
            options={options}
            loading={loading}
            disabled={disabled}
            placeholder="Select teams"
            data-attr="select-linear-teams"
        />
    )
}
