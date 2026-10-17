import type { ReactElement } from 'react'

import { formatClock, formatMonthDay } from '@/lib/dates'
import {
    type AppVariant,
    appVariant,
    type HostKind,
    hostKind,
    updateChannel,
    updateCreatedAt,
    updateId,
} from '@/lib/environment'

import { SettingsGroup } from './SettingsGroup'
import { SettingsRow } from './SettingsRow'

const VARIANT_NAMES: Record<AppVariant, string> = {
    development: 'Development',
    preview: 'Preview',
    production: 'Production',
}

const HOST_KIND_NAMES: Record<HostKind, string> = {
    'cloud-us': 'US cloud',
    'cloud-eu': 'EU cloud',
    local: 'Local',
    custom: 'Self-hosted',
}

function updateLabel(): string {
    if (!updateId) {
        return __DEV__ ? 'Metro bundle' : 'Built in'
    }
    const short = updateId.slice(0, 8)
    return updateCreatedAt ? `${short} · ${formatMonthDay(updateCreatedAt)}, ${formatClock(updateCreatedAt)}` : short
}

/** Internal builds only: which build, update and API host this device runs. */
export function EnvironmentGroup({ host }: { host: string | null }): ReactElement {
    return (
        <SettingsGroup title="Environment" testID="settings-environment">
            <SettingsRow label="Build" value={VARIANT_NAMES[appVariant]} />
            <SettingsRow label="Update channel" value={updateChannel ?? (__DEV__ ? 'Metro' : 'None')} />
            <SettingsRow label="Update" value={updateLabel()} monoValue={updateId !== null} />
            <SettingsRow label="API host" value={host ? HOST_KIND_NAMES[hostKind(host)] : 'Not signed in'} />
        </SettingsGroup>
    )
}
