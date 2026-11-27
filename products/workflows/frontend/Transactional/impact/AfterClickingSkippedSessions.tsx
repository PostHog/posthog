import { pluralize } from 'lib/utils/strings'

import type { ScanSkips } from './afterClickingScanLogic'

const REASONS: { key: keyof ScanSkips; reason: string }[] = [
    { key: 'busy', reason: 'because Replay vision is busy. Ask again later to scan them.' },
    { key: 'quota', reason: 'because your organization ran out of Replay vision credits.' },
    { key: 'questionLimit', reason: 'because this question reached its Replay vision credit limit for this period.' },
    { key: 'unscannable', reason: "because Replay vision couldn't watch their recordings." },
]

export function AfterClickingSkippedSessions({ skipped }: { skipped: ScanSkips }): JSX.Element {
    return (
        <>
            {REASONS.filter(({ key }) => skipped[key] > 0).map(({ key, reason }) => (
                <span key={key} className="text-secondary text-sm">
                    <span>{skipped[key]}</span> {pluralize(skipped[key], 'session', 'sessions', false)} weren't scanned{' '}
                    {reason}
                </span>
            ))}
        </>
    )
}
