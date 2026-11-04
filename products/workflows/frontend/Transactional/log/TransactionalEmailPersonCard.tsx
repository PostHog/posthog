import { useValues } from 'kea'

import { LemonButton, LemonSkeleton, ProfilePicture } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import { asDisplay } from 'products/persons/frontend/person-utils'

import { transactionalEmailLogEntryLogic } from './transactionalEmailLogEntryLogic'

function PropertyRow({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex justify-between gap-4 text-sm min-w-0">
            <dt className="text-secondary shrink-0">{label}</dt>
            <dd className="m-0 text-right truncate min-w-0">{children}</dd>
        </div>
    )
}

function location(properties: Record<string, any>): string | null {
    const parts = [properties.$geoip_city_name, properties.$geoip_country_name].filter(Boolean)
    return parts.length ? parts.join(', ') : null
}

export function TransactionalEmailPersonCard({ distinctId }: { distinctId: string }): JSX.Element {
    const { person, personLoading, personFailed } = useValues(transactionalEmailLogEntryLogic)

    if (personFailed && !personLoading) {
        return (
            <div className="border rounded bg-surface-primary p-4 flex flex-col gap-2">
                <h3 className="text-sm font-semibold m-0">Person</h3>
                <p className="text-sm text-secondary m-0">
                    This person couldn't load. Try again from the activity panel.
                </p>
            </div>
        )
    }

    if (person === undefined || personLoading) {
        return (
            <div className="border rounded bg-surface-primary p-4 flex flex-col gap-3">
                <div className="flex items-center gap-3">
                    <LemonSkeleton.Circle className="size-10" />
                    <div className="flex flex-col gap-2 flex-1">
                        <LemonSkeleton className="h-4 w-3/4" />
                        <LemonSkeleton className="h-3 w-1/2" />
                    </div>
                </div>
                <LemonSkeleton className="h-16" />
            </div>
        )
    }

    if (person === null) {
        return (
            <div className="border rounded bg-surface-primary p-4 flex flex-col gap-2">
                <h3 className="text-sm font-semibold m-0">Person</h3>
                <p className="text-sm text-secondary m-0">
                    No person in this project has the distinct ID <code className="break-all">{distinctId}</code> yet.
                    They show up here once your app captures an event for them.
                </p>
            </div>
        )
    }

    const { properties } = person
    const email = typeof properties.email === 'string' ? properties.email : null
    const name =
        typeof properties.name === 'string' && properties.name.trim()
            ? properties.name
            : asDisplay({ id: person.id, distinct_id: distinctId, properties })
    const place = location(properties)
    const plan = typeof properties.plan === 'string' ? properties.plan : null

    return (
        <div
            className="ph-no-capture border rounded bg-surface-primary p-4 flex flex-col gap-4"
            data-attr="transactional-email-person"
        >
            <div className="flex items-center gap-3 min-w-0">
                <ProfilePicture user={{ first_name: name, email: email ?? undefined }} size="xl" />
                <div className="flex flex-col min-w-0">
                    <span className="font-semibold truncate">{name}</span>
                    {email && email !== name && <span className="text-xs text-secondary truncate">{email}</span>}
                </div>
            </div>
            <dl className="flex flex-col gap-2 m-0">
                {plan && <PropertyRow label="Plan">{plan}</PropertyRow>}
                {place && <PropertyRow label="Location">{place}</PropertyRow>}
                <PropertyRow label="First seen">
                    <TZLabel time={person.createdAt} />
                </PropertyRow>
            </dl>
            <LemonButton
                type="secondary"
                size="small"
                fullWidth
                center
                to={urls.personByUUID(person.id)}
                data-attr="transactional-email-log-person"
            >
                View person
            </LemonButton>
        </div>
    )
}
