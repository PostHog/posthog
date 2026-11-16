import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonTag, Spinner } from '@posthog/lemon-ui'

import { codeEmailLogic } from './codeEmailLogic'

function fileName(path: string): string {
    return path.slice(path.lastIndexOf('/') + 1)
}

/** The files in the team's GitHub repositories that use this email's key, to pick one as its source file. */
export function SourceCandidatePicker(): JSX.Element {
    const { sourceCandidates, sourceCandidatesLoading, sourceCandidatesError, saving } = useValues(codeEmailLogic)
    const { findSourceCandidates, pickSourceCandidate, setSourceFormOpen } = useActions(codeEmailLogic)
    const incomplete = sourceCandidates?.complete === false

    return (
        <div className="flex flex-col gap-2 p-2 w-120 max-w-full" data-attr="code-email-source-picker">
            <div className="font-semibold">Pick the file that sends this email</div>
            {sourceCandidatesLoading ? (
                <div className="flex items-center gap-2 text-secondary py-2">
                    <Spinner />
                    Searching your GitHub repos for this key
                </div>
            ) : sourceCandidatesError ? (
                <LemonBanner
                    type="error"
                    action={
                        sourceCandidatesError.canRetry
                            ? { children: 'Try again', onClick: findSourceCandidates }
                            : undefined
                    }
                >
                    {sourceCandidatesError.message}
                </LemonBanner>
            ) : !sourceCandidates?.candidates.length ? (
                <p className="m-0 text-secondary">
                    {incomplete
                        ? "GitHub didn't finish the search, so a file may be missing. Paste a link instead."
                        : 'No file in your GitHub repos uses this key.'}
                </p>
            ) : (
                <>
                    {incomplete ? (
                        <LemonBanner type="info">
                            GitHub didn't finish the search, so a file may be missing.
                        </LemonBanner>
                    ) : null}
                    <ul className="flex flex-col gap-1 max-h-80 overflow-y-auto">
                        {sourceCandidates.candidates.map((candidate) => (
                            <li key={candidate.url}>
                                <LemonButton
                                    fullWidth
                                    size="small"
                                    onClick={() => pickSourceCandidate(candidate)}
                                    disabledReason={saving ? 'Saving' : undefined}
                                    sideIcon={
                                        candidate.call_site ? (
                                            <LemonTag type="success" size="small">
                                                Sends email
                                            </LemonTag>
                                        ) : null
                                    }
                                    data-attr="code-email-source-candidate"
                                >
                                    <span className="flex flex-col min-w-0" title={candidate.path}>
                                        <span className="font-mono truncate">
                                            {fileName(candidate.path)}:{candidate.line}
                                        </span>
                                        <span className="text-secondary text-xs font-normal truncate">
                                            {candidate.repository}/{candidate.path}
                                        </span>
                                    </span>
                                </LemonButton>
                            </li>
                        ))}
                    </ul>
                </>
            )}
            <div className="flex justify-end">
                <LemonButton
                    size="small"
                    type="tertiary"
                    onClick={() => setSourceFormOpen(true)}
                    data-attr="code-email-source-picker-paste-link"
                >
                    Paste a link instead
                </LemonButton>
            </div>
        </div>
    )
}
