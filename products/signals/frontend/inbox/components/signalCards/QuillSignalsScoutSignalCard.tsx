import { useState } from 'react'

import { IconExternal, IconList } from '@posthog/icons'
import { Button, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'
import { identifierToHuman } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import type {
    SignalsScoutEvidenceEntryApi,
    SignalsScoutSignalExtraApi,
} from 'products/signals/frontend/generated/api.schemas'

import { signalEntityUrl } from '../../utils/signalLinks'
import { getSourceProductMeta } from '../badges/sourceProductIcons'
import { QuillSignalCardLink } from './QuillSignalCardLink'
import { QuillSignalCardMarkdown } from './QuillSignalCardMarkdown'
import { QuillSignalCardShell } from './QuillSignalCardShell'
import { EVIDENCE_PREVIEW_COUNT, scoutHypothesis, scoutTaskRunUrl, truncatedMonoId } from './signalCardParsing'
import type { SignalCardProps } from './types'

/** A single evidence row: source icon + eyebrow, the summary, and an optional deep link. */
function QuillEvidenceRow({ entry }: { entry: SignalsScoutEvidenceEntryApi }): JSX.Element {
    const meta = getSourceProductMeta(entry.source_product)
    const url = signalEntityUrl(entry.source_product, entry.entity_id)
    return (
        <li className="flex items-start gap-2 py-0.5">
            <span className="mt-0.5 inline-flex shrink-0 items-center text-muted-foreground" aria-hidden>
                {meta ? <meta.Icon className={meta.colorClass} /> : <IconList />}
            </span>
            <div className="flex min-w-0 flex-1 flex-col">
                <Text size="xs" weight="medium" variant="muted" render={<span />}>
                    {meta?.label ?? identifierToHuman(entry.source_product)}
                </Text>
                <Text size="xs" render={<span />} className="break-words">
                    {entry.summary}
                </Text>
            </div>
            {url && (
                <QuillSignalCardLink to={url}>
                    View
                    <IconExternal />
                </QuillSignalCardLink>
            )}
        </li>
    )
}

/** Truncated mono identifier for footer run/finding ids. Becomes a deep link when `to` is set. */
function QuillMonoId({ label, value, to }: { label: string; value: string; to?: string }): JSX.Element {
    const display = truncatedMonoId(value)
    if (to) {
        return (
            <Button
                variant="link"
                size="inline"
                nativeButton={false}
                render={<LinkPrimitive to={to} />}
                className="font-medium"
            >
                <span>{label}</span>
                <span className="font-mono">{display}</span>
                <IconExternal />
            </Button>
        )
    }
    return (
        <span className="inline-flex items-center gap-1">
            <span>{label}</span>
            <span className="font-mono">{display}</span>
        </span>
    )
}

/** Quill sibling of `SignalsScoutSignalCard`: a cross-source scout finding with hypothesis, evidence, and run metadata. */
export function QuillSignalsScoutSignalCard({ signal }: SignalCardProps): JSX.Element {
    const [showAllEvidence, setShowAllEvidence] = useState(false)

    const extra = signal.extra as Record<string, unknown> & SignalsScoutSignalExtraApi

    const hypothesis = scoutHypothesis(signal, extra)

    const evidence = extra.evidence ?? []
    const visibleEvidence = showAllEvidence ? evidence : evidence.slice(0, EVIDENCE_PREVIEW_COUNT)

    const timeRange = extra.time_range
    const taskRunUrl = scoutTaskRunUrl(extra)

    return (
        <QuillSignalCardShell
            signal={signal}
            // The scout's name lives in the shared source line ("Scout · <name>"); keep just a linked
            // version here so the header doesn't repeat the name.
            label={
                <LinkPrimitive
                    to={urls.inboxScout(extra.skill_name)}
                    className="font-normal text-muted-foreground hover:underline"
                >
                    {`v${extra.skill_version}`}
                </LinkPrimitive>
            }
        >
            {hypothesis && <QuillSignalCardMarkdown className="text-foreground">{hypothesis}</QuillSignalCardMarkdown>}

            {timeRange && (
                <Text size="xs" variant="muted" className="m-0">
                    {humanFriendlyDetailedTime(timeRange.date_from)} to {humanFriendlyDetailedTime(timeRange.date_to)}
                </Text>
            )}

            {evidence.length > 0 && (
                <div className="flex flex-col gap-1 border-t border-border pt-2">
                    <Text size="xs" weight="medium" variant="muted" className="m-0">
                        Evidence
                    </Text>
                    <ul className="m-0 flex list-none flex-col p-0">
                        {visibleEvidence.map((entry, index) => (
                            <QuillEvidenceRow
                                key={`${entry.source_product}-${entry.entity_id ?? index}`}
                                entry={entry}
                            />
                        ))}
                    </ul>
                    {evidence.length > EVIDENCE_PREVIEW_COUNT && (
                        <Button size="sm" onClick={() => setShowAllEvidence(!showAllEvidence)} className="self-start">
                            {showAllEvidence ? 'Show fewer' : `Show all ${evidence.length}`}
                        </Button>
                    )}
                </div>
            )}

            {/* Footer — run/finding identifiers and an optional trace link-out. */}
            <Text
                size="xs"
                variant="muted"
                render={<div />}
                className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-border pt-2"
            >
                <QuillMonoId label="Signal" value={extra.finding_id} />
                <QuillMonoId label="Scout run" value={extra.scout_run_id} />
                {extra.task_id && <QuillMonoId label="Task" value={extra.task_id} to={taskRunUrl} />}
                <QuillMonoId label="Task run" value={extra.task_run_id} to={taskRunUrl} />
                {extra.mcp_trace_id && (
                    <span className="ms-auto">
                        <QuillSignalCardLink to={urls.aiObservabilityTrace(extra.mcp_trace_id)}>
                            View LLM trace
                            <IconExternal />
                        </QuillSignalCardLink>
                    </span>
                )}
            </Text>
        </QuillSignalCardShell>
    )
}
