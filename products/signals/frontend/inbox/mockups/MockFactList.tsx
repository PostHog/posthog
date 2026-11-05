import type { ReactNode } from 'react'

export interface MockFact {
    term: string
    value: ReactNode
}

export function MockFactList({ facts }: { facts: MockFact[] }): JSX.Element {
    return (
        <dl className="InboxMockup__facts">
            {facts.map(({ term, value }) => (
                <div key={term} className="InboxMockup__fact">
                    <dt>{term}</dt>
                    <dd>{value}</dd>
                </div>
            ))}
        </dl>
    )
}
