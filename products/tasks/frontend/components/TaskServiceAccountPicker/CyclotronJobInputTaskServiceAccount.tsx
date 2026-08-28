import { useValues } from 'kea'

import { LemonSelect, Link } from '@posthog/lemon-ui'

import type { CustomInputRendererProps } from 'lib/components/CyclotronJob/customInputRenderers'
import { urls } from 'scenes/urls'

import { taskServiceAccountPickerLogic } from './taskServiceAccountPickerLogic'

export default function CyclotronJobInputTaskServiceAccount({
    value,
    onChange,
}: CustomInputRendererProps): JSX.Element {
    const { serviceAccounts, serviceAccountsLoading } = useValues(taskServiceAccountPickerLogic)

    const selectedId: string | null = typeof value === 'string' && value ? value : null

    const options: { value: string; label: string; disabledReason?: string }[] = serviceAccounts.map((account) => ({
        value: account.id,
        label: account.name,
        disabledReason: account.status !== 'active' ? 'This service account is paused.' : undefined,
    }))
    // The stored id may name a service account since deleted; still render it so the person
    // editing can see it and clear the field.
    if (selectedId && !options.some((option) => option.value === selectedId)) {
        options.push({ value: selectedId, label: `Unavailable service account (${selectedId})` })
    }

    return (
        <div className="flex items-center gap-2 flex-wrap">
            <LemonSelect
                value={selectedId}
                options={options}
                onChange={(id) => onChange(id ?? undefined)}
                loading={serviceAccountsLoading}
                placeholder="No service account"
                allowClear
                data-attr="task-service-account-picker"
            />
            <Link to={urls.mcpGatewayTab('team')} target="_blank">
                Manage service accounts
            </Link>
        </div>
    )
}
