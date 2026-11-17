// PROTOTYPE (ticket #385), throwaway. Small pieces the list variants share: a sparkline, a mini funnel, the
// conversion and the Replay vision state of one email, and one-click actions.
import { useState } from 'react'

import { IconLock, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { SCANNER_SUGGESTIONS } from './ImpactFindings'
import { percent } from './impactFixtures'
import { LINK_TAG_DETAIL } from './ImpactFunnel'
import { conversionRate, ListEmail } from './listFixtures'
import { journeyUrl, useEmailJourneyPrototype } from './useEmailJourneyPrototype'

/** Every email opens the one impact page the prototype has. */
export function impactUrl(email: ListEmail, extra?: 'no-goal'): string {
    return journeyUrl('D', extra ?? (email.goal ? null : 'no-goal'))
}

export function EmailName({ email }: { email: ListEmail }): JSX.Element {
    return (
        <div className="flex flex-col py-1">
            <span className="flex flex-wrap items-center gap-1 font-semibold text-sm">
                <Link subtle to={impactUrl(email)} className={email.source === 'code' ? 'font-mono' : undefined}>
                    {email.name}
                </Link>
                {email.source === 'code' && <LemonTag size="small">Code</LemonTag>}
                {email.clicked === null && (
                    <LemonTag type="highlight" size="small" icon={<IconLock />}>
                        Sensitive
                    </LemonTag>
                )}
            </span>
            <span className="text-xs text-tertiary">{email.description}</span>
        </div>
    )
}

export function Sparkline({ values, className }: { values: number[]; className?: string }): JSX.Element {
    const max = Math.max(1, ...values)
    const points = values.map((value, index) => `${(index / (values.length - 1)) * 100},${30 - (value / max) * 28}`)
    return (
        <svg viewBox="0 0 100 30" preserveAspectRatio="none" className={className ?? 'w-24 h-7'}>
            <polyline
                points={points.join(' ')}
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
                vectorEffect="non-scaling-stroke"
            />
        </svg>
    )
}

const MINI_STEPS: [keyof ListEmail, string][] = [
    ['sent', 'Sent'],
    ['opened', 'Opened'],
    ['clicked', 'Clicked'],
    ['landed', 'Started a session'],
    ['converted', 'Converted'],
]

export function MiniFunnel({ email, large = false }: { email: ListEmail; large?: boolean }): JSX.Element {
    return (
        <Link to={impactUrl(email)} subtle className="block">
            <div className={`flex items-end gap-0.5 ${large ? 'h-24 gap-2' : 'h-7 w-24'}`}>
                {MINI_STEPS.map(([key, label], index) => {
                    const value = email[key] as number | null
                    const name = key === 'converted' && email.goal ? email.goal : label
                    return (
                        <Tooltip
                            key={key}
                            title={`${name}: ${value === null ? 'not tracked' : humanFriendlyNumber(value)}`}
                        >
                            <div
                                className={`flex-1 h-full flex items-end ${large ? 'bg-surface-secondary rounded' : ''}`}
                            >
                                <div
                                    className={`w-full rounded-sm ${
                                        value === null
                                            ? 'bg-border'
                                            : index === MINI_STEPS.length - 1
                                              ? 'bg-success'
                                              : 'bg-accent'
                                    }`}
                                    style={{
                                        height: value === null ? '8%' : `${Math.max(4, (value / email.sent) * 100)}%`,
                                    }}
                                />
                            </div>
                        </Tooltip>
                    )
                })}
            </div>
            {large && (
                <div className="flex gap-2 mt-1">
                    {MINI_STEPS.map(([key, label]) => {
                        const value = email[key] as number | null
                        return (
                            <div key={key} className="flex-1 min-w-0 flex flex-col">
                                <span className="text-xs text-secondary truncate">
                                    {key === 'converted' && email.goal ? email.goal : label}
                                </span>
                                <span className="text-sm font-semibold">
                                    {value === null ? '-' : humanFriendlyNumber(value)}
                                </span>
                            </div>
                        )
                    })}
                </div>
            )}
        </Link>
    )
}

export function ConversionCell({ email }: { email: ListEmail }): JSX.Element {
    const rate = conversionRate(email)
    if (rate === null) {
        return email.clicked === null ? (
            <span className="text-secondary text-sm">Clicks not tracked</span>
        ) : (
            <Link to={impactUrl(email, 'no-goal')} className="text-sm">
                Pick an event
            </Link>
        )
    }
    return (
        <div className="flex flex-col">
            <span className="font-semibold">{percent(email.converted!, email.clicked ?? email.delivered)}</span>
            <span className="text-xs text-secondary">
                did "{email.goal}" after {email.clicked === null ? 'the send' : 'clicking'}
            </span>
        </div>
    )
}

/** Replay vision for one email: its findings, or one click to start watching the sessions it starts. */
export function ReplayVisionCell({ email }: { email: ListEmail }): JSX.Element {
    const { journeyCase } = useEmailJourneyPrototype()
    const [started, setStarted] = useState(false)

    if (email.scanner) {
        return (
            <Link to={impactUrl(email)} subtle className="flex flex-col">
                <span className="flex items-center gap-1 text-sm">
                    <IconSparkles className="text-warning" />
                    {email.scanner.problems} {email.scanner.problems === 1 ? 'problem' : 'problems'} found
                </span>
                {email.scanner.topProblem && (
                    <span className="text-xs text-secondary truncate max-w-56">{email.scanner.topProblem}</span>
                )}
            </Link>
        )
    }
    if (email.clicked === null) {
        return <span className="text-xs text-secondary">Needs click tracking</span>
    }
    if (journeyCase === 'no-landing') {
        return (
            <Tooltip title={LINK_TAG_DETAIL}>
                <span className="text-xs text-secondary underline decoration-dotted cursor-help">
                    Needs link tagging
                </span>
            </Tooltip>
        )
    }
    if (journeyCase === 'no-recording') {
        return <span className="text-xs text-secondary">Needs session replay</span>
    }
    if (started) {
        return (
            <Tooltip title={`Watching the sessions this email starts: "${SCANNER_SUGGESTIONS[0].question}"`}>
                <LemonTag type="highlight" icon={<IconSparkles />}>
                    Watching sessions
                </LemonTag>
            </Tooltip>
        )
    }
    return (
        <LemonButton
            size="xsmall"
            type="secondary"
            icon={<IconSparkles />}
            onClick={() => setStarted(true)}
            tooltip={`Starts a Replay vision scanner on the sessions this email starts: "${SCANNER_SUGGESTIONS[0].question}"`}
            data-attr="prototype-list-turn-on-scanner"
        >
            Watch sessions
        </LemonButton>
    )
}
