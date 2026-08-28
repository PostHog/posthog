import { useActions, useValues } from 'kea'

import { githubRepositorySearchLogic } from 'lib/integrations/githubRepositorySearchLogic'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect'

/**
 * "Which repository should it have been?" form field, shown in the dismiss dialog when the
 * reason is `wrong_repo`. Renders nothing when the team has no GitHub integration, since there
 * is no candidate list to pick from; the dismissal is still recorded without a correction.
 */
export function DismissCorrectedRepoField(): JSX.Element | null {
    const { githubIntegrations } = useValues(integrationsLogic)
    // The team's first GitHub integration — a convenience list, not the backend's resolution.
    // A correction teaches the selection agent regardless of whether the named repository is
    // connected; only the optional "pin as this report's next selection" needs connectivity.
    const integrationId = githubIntegrations[0]?.id
    if (integrationId == null) {
        return null
    }
    return <CorrectedRepoPicker integrationId={integrationId} />
}

function CorrectedRepoPicker({ integrationId }: { integrationId: number }): JSX.Element {
    const logic = githubRepositorySearchLogic({ id: integrationId })
    const { repositoryNames, loading, error } = useValues(logic)
    const { setSearchQuery } = useActions(logic)

    return (
        <LemonField
            name="correctedRepository"
            label="Which repository should it have been?"
            info="Optional. The agent uses your correction when picking repositories in the future."
        >
            {({ value, onChange }) => (
                <div className="flex items-center gap-2">
                    {/* LemonInputSelect selects the highlighted repository on Enter but lets the event
                        bubble. Stop it so the surrounding LemonFormDialog does not submit on the same
                        Enter with a pre-selection form snapshot, archiving the report with no correction. */}
                    <div
                        className="flex-1"
                        onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                                e.stopPropagation()
                            }
                        }}
                    >
                        <LemonInputSelect
                            mode="single"
                            value={value ? [value] : []}
                            onChange={(newValues) => onChange(newValues[0] ?? null)}
                            options={repositoryNames.map((name) => ({ key: name.toLowerCase(), label: name }))}
                            onInputChange={setSearchQuery}
                            loading={loading}
                            placeholder="Search repositories"
                            data-attr="inbox-dismiss-corrected-repository"
                            // Without this a failed lookup shows the generic "No options", which reads as
                            // an account with no repositories. Typing clears the error and retries.
                            emptyStateComponent={error ? <p className="text-danger italic p-1">{error}</p> : undefined}
                        />
                    </div>
                    {/* Single-mode LemonInputSelect without allowCustomValues renders no clear button, so
                        give pointer users an explicit way back to "no correction" (Backspace also works). */}
                    {value && (
                        <LemonButton
                            type="secondary"
                            onClick={() => onChange(null)}
                            data-attr="inbox-dismiss-corrected-repository-clear"
                        >
                            Clear
                        </LemonButton>
                    )}
                </div>
            )}
        </LemonField>
    )
}
