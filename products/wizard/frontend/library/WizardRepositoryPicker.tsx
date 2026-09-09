import { useActions, useValues } from 'kea'

import { IconCheck, IconRefresh, IconSearch } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonSkeleton, Spinner } from '@posthog/lemon-ui'

import { githubRepositorySearchLogic } from 'lib/integrations/githubRepositorySearchLogic'

export function WizardRepositoryPicker({
    integrationId,
    value,
    onChange,
    disabledReason,
}: {
    integrationId: number
    value: string
    onChange: (repository: string) => void
    disabledReason?: string
}): JSX.Element {
    const logic = githubRepositorySearchLogic({ id: integrationId })
    const { repositories, loading, hasMore, searchQuery, error } = useValues(logic)
    const { setSearchQuery, loadMore, refresh } = useActions(logic)

    // Archived and read-only repositories cannot receive the run's pull request.
    const eligible = repositories.filter((repository) => !repository.archived && repository.can_push !== false)

    return (
        <div className="flex flex-col gap-1">
            <LemonInput
                value={searchQuery}
                onChange={setSearchQuery}
                prefix={<IconSearch />}
                placeholder="Search repositories"
                fullWidth
                data-attr="wizard-cloud-repository-search"
            />
            {error ? (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: refresh }}>
                    {error}
                </LemonBanner>
            ) : loading && repositories.length === 0 ? (
                <LemonSkeleton repeat={3} className="h-10 w-full" />
            ) : (
                <div className="max-h-44 overflow-y-auto rounded border border-primary">
                    {eligible.length === 0 ? (
                        <p className="m-0 px-3 py-2 text-sm text-muted">
                            {searchQuery ? 'No matching repositories.' : 'No repositories available.'}
                        </p>
                    ) : (
                        eligible.map((repository) => (
                            <LemonButton
                                key={repository.id}
                                onClick={() => onChange(repository.full_name)}
                                active={repository.full_name === value}
                                disabledReason={disabledReason}
                                fullWidth
                                icon={repository.full_name === value ? <IconCheck /> : undefined}
                                className="justify-start"
                                data-attr="wizard-cloud-repository-option"
                            >
                                {repository.full_name}
                            </LemonButton>
                        ))
                    )}
                </div>
            )}
            <div className="flex items-center gap-2">
                {hasMore && !error && (
                    <LemonButton size="small" onClick={loadMore} loading={loading} disabledReason={disabledReason}>
                        Load more
                    </LemonButton>
                )}
                {hasMore && !error && !loading && (
                    <LemonButton size="small" icon={<IconRefresh />} onClick={refresh} disabledReason={disabledReason}>
                        Refresh
                    </LemonButton>
                )}
                {loading && repositories.length > 0 && <Spinner className="size-4" />}
            </div>
        </div>
    )
}
