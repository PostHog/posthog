import { LemonTag } from '@posthog/lemon-ui'

export function ComingSoonInterestTag({ hasRecordedInterest }: { hasRecordedInterest: boolean }): JSX.Element {
    return (
        <LemonTag type={hasRecordedInterest ? 'success' : 'muted'} className="whitespace-nowrap">
            {hasRecordedInterest ? 'Interest noted' : 'Coming soon'}
        </LemonTag>
    )
}
