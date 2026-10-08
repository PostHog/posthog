import { SetupFactsTable } from '../SetupFactsTable'
import type { IdentityFact } from '../setupInspectorUtils'

export function IdentitySummarySection({ facts }: { facts: IdentityFact[] }): JSX.Element {
    return (
        <section className="flex flex-col gap-2">
            <h3 className="mb-0">Identity and bucketing</h3>
            <p className="text-secondary text-sm mb-0">
                The facts behind most identity and bucketing questions, taken from the SDK profile and the target
                surface below.
            </p>
            <SetupFactsTable facts={facts} />
        </section>
    )
}
