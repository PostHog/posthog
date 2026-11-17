// PROTOTYPE (ticket #385), throwaway. Replay vision on the email page: a scanner scoped to the sessions this email
// started, its findings with excerpts and recordings, and the setup card when there is no scanner yet.
import { useState } from 'react'

import { IconCheckCircle, IconPlayFilled, IconSparkles, IconWarning } from '@posthog/icons'
import { LemonButton, LemonSelect, LemonTag, LemonTextArea, Link } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { ImpactData, ImpactFinding, percent } from './impactFixtures'
import { LINK_TAG_DETAIL } from './ImpactFunnel'
import type { JourneySession } from './journeyFixtures'
import { journeyUrl, useEmailJourneyPrototype } from './useEmailJourneyPrototype'

function clock(seconds: number): string {
    return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

const TONE_ICON = {
    problem: <IconWarning className="text-warning text-lg shrink-0" />,
    success: <IconCheckCircle className="text-success text-lg shrink-0" />,
    neutral: <IconSparkles className="text-secondary text-lg shrink-0" />,
}

export function FindingCard({
    finding,
    data,
    onWatch,
    excerpts = 1,
}: {
    finding: ImpactFinding
    data: ImpactData
    onWatch: (session: JourneySession) => void
    excerpts?: number
}): JSX.Element {
    const link = data.links.find((l) => l.key === finding.linkKey)
    const scanned = data.scanner?.scanned ?? 0
    return (
        <div className="border rounded bg-surface-primary p-3 flex flex-col gap-2" data-attr="prototype-impact-finding">
            <div className="flex items-start gap-2">
                {TONE_ICON[finding.tone]}
                <div className="flex-1 min-w-0 flex flex-col">
                    <span className="font-semibold text-sm">{finding.title}</span>
                    <span className="text-xs text-secondary">
                        {humanFriendlyNumber(finding.sessions)} sessions · {percent(finding.sessions, scanned)} of
                        scanned{link ? ` · from "${link.label}"` : ''}
                    </span>
                </div>
            </div>
            {finding.excerpts.slice(0, excerpts).map((excerpt) => (
                <div key={excerpt.session.id} className="flex gap-2 items-start bg-surface-secondary rounded p-2">
                    <div className="flex-1 min-w-0 flex flex-col gap-0.5">
                        <span className="text-sm">{excerpt.text}</span>
                        <span className="text-xs text-secondary">
                            {excerpt.person} · <Link to={journeyUrl('A')}>Open this send</Link>
                        </span>
                    </div>
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        icon={<IconPlayFilled />}
                        onClick={() => onWatch(excerpt.session)}
                        data-attr="prototype-impact-watch"
                    >
                        {clock(excerpt.atSeconds)}
                    </LemonButton>
                </div>
            ))}
            <LemonButton size="xsmall" type="tertiary" to={urls.replayVision()} className="self-start">
                See all {humanFriendlyNumber(finding.sessions)} sessions
            </LemonButton>
        </div>
    )
}

/** What's blocking a scanner, if anything. */
export function scannerBlocked(data: ImpactData): string | null {
    if (data.clicked === null) {
        return "Clicks aren't tracked for this email, so PostHog can't tell which sessions it started."
    }
    if (!data.runTagOn) {
        return LINK_TAG_DETAIL.replace(' Conversions still count, because they go through the person on each send.', '')
    }
    if (!data.recordingsOn) {
        return 'Replay vision watches recordings, and session replay is off for this project.'
    }
    return null
}

export function ScannerStatus({ data }: { data: ImpactData }): JSX.Element | null {
    const scanner = data.scanner
    if (!scanner) {
        return null
    }
    const total = data.landed ?? 0
    const scanning = scanner.scanned < total * 0.5
    return (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-secondary">
            <LemonTag type="highlight" icon={<IconSparkles />}>
                Replay vision
            </LemonTag>
            <span>
                {scanner.type}: "{scanner.prompt}"
            </span>
            <span>
                Scanned {humanFriendlyNumber(scanner.scanned)} of {humanFriendlyNumber(total)} sessions from this email
            </span>
            {scanning && <LemonProgress percent={(scanner.scanned / total) * 100} className="w-24" />}
            <LemonButton size="xsmall" type="tertiary" to={urls.replayVision()}>
                Edit scanner
            </LemonButton>
        </div>
    )
}

const SETUP_TYPES = [
    { value: 'classifier', label: 'Categorize' },
    { value: 'summarizer', label: 'Summarize' },
    { value: 'monitor', label: 'Ask a question' },
]

export function ScannerSetup({ data }: { data: ImpactData }): JSX.Element {
    const { set } = useEmailJourneyPrototype()
    const [type, setType] = useState('classifier')
    const [prompt, setPrompt] = useState(
        data.goal
            ? `What did the person do after landing from this email, and what stopped them from doing "${data.goal.event}"?`
            : 'What did the person do after landing from this email, and what stopped them?'
    )
    const blocked = scannerBlocked(data)

    return (
        <div className="border rounded bg-surface-primary p-4 flex flex-col gap-3" data-attr="prototype-impact-setup">
            <div className="flex items-start gap-2">
                <IconSparkles className="text-lg shrink-0 mt-0.5" />
                <div className="flex flex-col gap-0.5">
                    <span className="font-semibold">See what people do after they click</span>
                    <span className="text-sm text-secondary">
                        A Replay vision scanner watches only the sessions this email starts and groups what happened, so
                        you don't have to watch them one by one.
                    </span>
                </div>
            </div>
            {blocked ? (
                <p className="text-sm text-secondary m-0">{blocked}</p>
            ) : (
                <>
                    <div className="flex flex-wrap items-center gap-2">
                        <LemonSelect size="small" value={type} onChange={setType} options={SETUP_TYPES} />
                        <span className="text-xs text-secondary">
                            About {humanFriendlyNumber(data.landed ?? 0)} sessions in the {data.period.toLowerCase()}
                        </span>
                    </div>
                    <LemonTextArea value={prompt} onChange={setPrompt} minRows={2} />
                    <div className="flex gap-2">
                        <LemonButton
                            type="primary"
                            size="small"
                            onClick={() => set({ case: 'scanning' })}
                            data-attr="prototype-impact-start-scanner"
                        >
                            Start scanner
                        </LemonButton>
                        <LemonButton type="secondary" size="small" to={urls.replayVision()}>
                            Use a saved scanner
                        </LemonButton>
                    </div>
                </>
            )}
        </div>
    )
}

export function ScannerSummary({ data }: { data: ImpactData }): JSX.Element | null {
    if (!data.scanner) {
        return null
    }
    return data.scanner.summary ? (
        <p className="text-base m-0">{data.scanner.summary}</p>
    ) : (
        <p className="text-sm text-secondary m-0">
            The scanner has watched {data.scanner.scanned} sessions so far. Findings firm up as it watches more, and the
            summary shows once it has enough.
        </p>
    )
}
