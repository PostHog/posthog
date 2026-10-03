import type { RecipientApi } from 'products/messaging/frontend/generated/api.schemas'

export function RecipientPersonsSummary({ recipient }: { recipient: RecipientApi }): JSX.Element {
    const { person_count: personCount, persons } = recipient
    if (personCount === 0) {
        return <span className="text-xs text-secondary">No person</span>
    }
    if (personCount === 1 && persons.length === 1) {
        return <span className="wrap-anywhere">{persons[0].name ?? persons[0].distinct_id}</span>
    }
    return <span>{personCount === 1 ? '1 person' : `${personCount.toLocaleString()} persons`}</span>
}
