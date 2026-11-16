import { LemonBanner } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import type { PushTokenImportApi } from 'products/workflows/frontend/generated/api.schemas'
import { PushTokenImportStatusEnumApi } from 'products/workflows/frontend/generated/api.schemas'

function counted(count: number, one: string, many: string): string {
    return `${count.toLocaleString()} ${pluralize(count, one, many, false)}`
}

/** Says how a finished import ended and how many devices it stored. */
export function PushTokenImportOutcomeBanner({ job }: { job: PushTokenImportApi }): JSX.Element {
    const imported = `${counted(job.imported_devices, 'device', 'devices')} imported.`
    if (job.status === PushTokenImportStatusEnumApi.Failed) {
        return (
            <LemonBanner type="error">
                {job.error} {imported}
            </LemonBanner>
        )
    }
    if (job.status === PushTokenImportStatusEnumApi.Cancelled) {
        return <LemonBanner type="warning">You stopped the import. {imported}</LemonBanner>
    }
    const notImported = job.failed_devices
        ? ` ${counted(job.failed_devices, 'line was', 'lines were')} not imported.`
        : ''
    const duplicates = job.duplicate_lines
        ? ` ${counted(job.duplicate_lines, 'repeated line was', 'repeated lines were')} left out.`
        : ''
    return (
        <LemonBanner type={job.failed_devices ? 'warning' : 'success'}>
            {imported}
            {notImported}
            {duplicates}
        </LemonBanner>
    )
}
