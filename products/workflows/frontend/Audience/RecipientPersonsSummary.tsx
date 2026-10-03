import type { RecipientApi } from 'products/messaging/frontend/generated/api.schemas'

export function RecipientPersonsSummary({ recipient }: { recipient: RecipientApi }): JSX.Element {
    const { person_count: personCount, persons } = recipient
    if (personCount === 0) {
        return <span className="text-xs text-secondary">No person</span>
    }
    const onlyPersonLabel = personCount === 1 && (persons[0]?.name?.trim() || persons[0]?.distinct_id)
    if (onlyPersonLabel) {
        return <span className="wrap-anywhere">{onlyPersonLabel}</span>
    }
    return <span>{personCount === 1 ? '1 person' : `${personCount.toLocaleString()} persons`}</span>
}
