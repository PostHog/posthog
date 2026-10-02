import { useValues } from 'kea'

import { NotFound } from 'lib/components/NotFound'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { compactNumber } from 'lib/utils/numbers'

import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema/schema-general'
import { PersonType, PropertyDefinitionType } from '~/types'

import type { ObjectEmbedProps } from 'products/posthog_ai/frontend/api/types'

import { PersonIcon } from '../components/PersonDisplay'
import { personLogic } from '../logics/personLogic'
import { asDisplay, pickBestPersonDistinctId } from '../person-utils'

const KEY_PROPERTIES = [
    'email',
    'name',
    '$geoip_country_name',
    '$geoip_city_name',
    '$browser',
    '$os',
    '$device_type',
    '$initial_referring_domain',
    '$initial_utm_source',
]

function keyProperties(person: PersonType): Record<string, unknown> {
    const picked = Object.fromEntries(
        KEY_PROPERTIES.filter((key) => person.properties[key] != null).map((key) => [key, person.properties[key]])
    )
    return Object.keys(picked).length > 0 ? picked : person.properties
}

function PersonActivity({ personId }: { personId: string }): JSX.Element {
    const { info, infoLoading } = useValues(personLogic({ id: personId, distinctId: undefined }))
    if (infoLoading && !info) {
        return <LemonSkeleton className="h-4 w-48" />
    }
    if (!info) {
        return <></>
    }
    return (
        <span>
            {compactNumber(info.eventCount)} events and {compactNumber(info.sessionCount)} sessions in the last 30 days
        </span>
    )
}

/** A read-only person summary: name, distinct ID, key properties and recent events. */
export function PersonObjectEmbed({ objectId }: ObjectEmbedProps): JSX.Element {
    const { person, personLoading } = useValues(personLogic({ id: objectId, distinctId: undefined }))
    if (!person) {
        return personLoading ? (
            <div className="flex flex-col gap-2 p-4">
                <LemonSkeleton className="h-6 w-48" />
                <LemonSkeleton className="h-32" />
            </div>
        ) : (
            <NotFound object="person" />
        )
    }
    const distinctId = pickBestPersonDistinctId(person.distinct_ids)
    return (
        <div className="flex flex-col gap-4 p-4">
            <div className="flex items-start gap-3">
                <PersonIcon person={person} size="xl" />
                <div className="flex min-w-0 flex-col gap-1">
                    <span className="truncate font-semibold ph-no-capture">{asDisplay(person)}</span>
                    {distinctId ? (
                        <span className="truncate font-mono text-xs text-secondary ph-no-capture">{distinctId}</span>
                    ) : null}
                    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-secondary">
                        {person.created_at ? (
                            <span>
                                First seen <TZLabel time={person.created_at} />
                            </span>
                        ) : null}
                        {person.uuid ? <PersonActivity personId={person.uuid} /> : null}
                    </div>
                </div>
            </div>
            <div className="overflow-hidden rounded-md border border-primary bg-surface-primary">
                <PropertiesTable
                    properties={keyProperties(person)}
                    type={PropertyDefinitionType.Person}
                    sortProperties
                    embedded
                />
            </div>
            {person.uuid ? (
                <div className="flex flex-col gap-2">
                    <span className="text-sm font-semibold">Recent events</span>
                    <div className="overflow-hidden rounded-md border border-primary bg-surface-primary">
                        <Query
                            uniqueKey={`task-artifact-person-${person.uuid}`}
                            query={{
                                kind: NodeKind.DataTableNode,
                                full: false,
                                embedded: true,
                                showOpenEditorButton: false,
                                source: {
                                    kind: NodeKind.EventsQuery,
                                    select: defaultDataTableColumns(NodeKind.EventsQuery),
                                    personId: person.uuid,
                                    after: '-30d',
                                    limit: 10,
                                },
                            }}
                            readOnly
                        />
                    </div>
                </div>
            ) : null}
        </div>
    )
}
