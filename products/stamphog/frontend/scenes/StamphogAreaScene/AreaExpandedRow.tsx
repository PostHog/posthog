import { useValues } from 'kea'

import { IconExternal } from '@posthog/icons'
import { LemonCollapse, Link, Spinner } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'

import { Field } from '../../components/Field'
import { Section } from '../../components/Section'
import { TimeField } from '../../components/TimeField'
import { RoutingOwnerOutcomeEnumApi } from '../../generated/api.schemas'
import { AreaRow, otherOwnerStatus, whySentence, whyTitle } from './areaDisplay'
import { stamphogAreaSceneLogic } from './stamphogAreaSceneLogic'

export function AreaExpandedRow({ row }: { row: AreaRow }): JSX.Element {
    const { owner, runDetails } = useValues(stamphogAreaSceneLogic)
    const { run, decision } = row
    const files = runDetails[run.id]?.owners.find((entry) => entry.owner === owner)?.files
    const otherOwners = run.owners.filter((entry) => entry.owner !== owner)

    return (
        <div className="grid grid-cols-1 @min-[48rem]/main-content:grid-cols-2 gap-x-8 gap-y-6 pl-2 pr-4 py-4">
            <section className="min-w-0 flex flex-col gap-2">
                <h5 className="text-muted mb-0">Your part of the change</h5>
                {files ? (
                    <ul className="font-mono text-xs flex flex-col gap-0.5">
                        {files.map((file) => (
                            <li key={file.path} className="break-all">
                                {file.path}
                                {(file.additions ?? 0) > 0 ? (
                                    <span className="text-success">{` +${file.additions}`}</span>
                                ) : null}
                                {(file.deletions ?? 0) > 0 ? (
                                    <span className="text-danger">{` -${file.deletions}`}</span>
                                ) : null}
                            </li>
                        ))}
                    </ul>
                ) : (
                    <Spinner />
                )}
                <Link to={run.pull_request.url} target="_blank" className="self-start">
                    Open pull request <IconExternal />
                </Link>
            </section>

            <section className="min-w-0 flex flex-col gap-2 text-sm">
                <h5 className="text-muted mb-0">{whyTitle(decision.outcome)}</h5>
                <p className="mb-0">{whySentence(decision)}</p>
                {decision.outcome === RoutingOwnerOutcomeEnumApi.Cut && decision.model_reason ? (
                    <p className="mb-0 text-secondary">The model judged: {decision.model_reason}</p>
                ) : null}

                <h5 className="text-muted mb-0 mt-2">Other teams</h5>
                {otherOwners.length === 0 ? (
                    <span className="text-secondary">None</span>
                ) : (
                    <ul className="flex flex-col gap-0.5">
                        {otherOwners.map((entry) => (
                            <li key={entry.owner}>
                                <span className="font-mono text-xs">{entry.owner}</span>
                                <span className="text-secondary">{` · ${otherOwnerStatus(entry.outcome)}`}</span>
                            </li>
                        ))}
                    </ul>
                )}

                <LemonCollapse
                    size="small"
                    className="mt-2"
                    panels={[
                        {
                            key: 'routing',
                            header: 'Routing details',
                            content: (
                                <Section>
                                    <Field label="Run ID">
                                        <CopyToClipboardInline description="run ID" explicitValue={run.id}>
                                            {run.id.slice(0, 8)}
                                        </CopyToClipboardInline>
                                    </Field>
                                    <TimeField label="Routed" time={run.created_at} />
                                    <Field label="Trigger">{run.trigger}</Field>
                                    <Field label="Scope">{run.scope}</Field>
                                    <Field label="Model">{run.model || null}</Field>
                                    <Field label="Head commit">{run.head_sha}</Field>
                                </Section>
                            ),
                        },
                    ]}
                />
            </section>
        </div>
    )
}
