import { LemonButton } from '@posthog/lemon-ui'

export function TransactionalEmailImpactLink({ impactUrl }: { impactUrl: string }): JSX.Element {
    return (
        <section className="border rounded bg-surface-primary p-4 flex flex-col gap-2">
            <h3 className="text-sm font-semibold m-0">Across all its sends</h3>
            <p className="text-xs text-secondary m-0">
                See how far this email's sends got and what people did after them.
            </p>
            <div>
                <LemonButton
                    type="secondary"
                    size="small"
                    to={impactUrl}
                    data-attr="transactional-email-log-entry-open-impact"
                >
                    See this email's impact
                </LemonButton>
            </div>
        </section>
    )
}
