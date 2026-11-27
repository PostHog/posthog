import type { ScanSkips } from './afterClickingScanLogic'

const REASONS: { key: keyof ScanSkips; reason: (one: boolean) => string }[] = [
    { key: 'busy', reason: () => 'because Replay vision is busy. Ask again later.' },
    { key: 'quota', reason: () => 'because your organization ran out of Replay vision credits.' },
    {
        key: 'questionLimit',
        reason: () => 'because this question reached its Replay vision credit limit for this period.',
    },
    {
        key: 'unscannable',
        reason: (one) => `because Replay vision couldn't watch ${one ? 'its recording' : 'their recordings'}.`,
    },
]

export function AfterClickingSkippedSessions({ skipped }: { skipped: ScanSkips }): JSX.Element {
    return (
        <>
            {REASONS.filter(({ key }) => skipped[key] > 0).map(({ key, reason }) => {
                const one = skipped[key] === 1
                return (
                    <span key={key} className="text-secondary text-sm">
                        <span>{skipped[key]}</span> {one ? "session wasn't" : "sessions weren't"} scanned {reason(one)}
                    </span>
                )
            })}
        </>
    )
}
