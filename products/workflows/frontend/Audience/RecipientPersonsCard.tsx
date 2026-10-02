import { LemonCard, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { RecipientApi } from 'products/messaging/frontend/generated/api.schemas'

function MorePersons({ count }: { count: number }): JSX.Element | null {
    if (count <= 0) {
        return null
    }
    return (
        <span className="text-xs text-secondary">
            and {count === 1 ? '1 more person' : `${count.toLocaleString()} more persons`}
        </span>
    )
}

export function RecipientPersonsCard({ recipient }: { recipient: RecipientApi }): JSX.Element {
    const { persons, person_count: personCount } = recipient

    return (
        <LemonCard hoverEffect={false} className="flex-1 min-w-72 flex flex-col gap-1">
            <h3 className="font-semibold m-0">Linked persons</h3>
            {personCount === 0 ? (
                <p className="m-0 text-xs text-secondary">
                    No person has this email address. Topic preferences still apply when a workflow sends to it.
                </p>
            ) : (
                <>
                    <p className="m-0 text-xs text-secondary">Persons whose email property is this address.</p>
                    <div className="flex flex-col divide-y">
                        {persons.map((person) => (
                            <div key={person.uuid} className="flex flex-wrap items-center justify-between gap-x-2 py-1">
                                <Link to={urls.personByUUID(person.uuid)} className="font-medium wrap-anywhere">
                                    {person.name ?? person.distinct_id}
                                </Link>
                                {person.name && (
                                    <span className="text-xs text-secondary wrap-anywhere">{person.distinct_id}</span>
                                )}
                            </div>
                        ))}
                    </div>
                    <MorePersons count={personCount - persons.length} />
                </>
            )}
        </LemonCard>
    )
}
