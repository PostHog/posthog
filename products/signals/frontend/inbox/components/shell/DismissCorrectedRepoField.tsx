import { useActions, useValues } from 'kea'

import { githubRepositorySearchLogic } from 'lib/integrations/githubRepositorySearchLogic'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect'

/**
 * "Which repository should it have been?" form field, shown in the dismiss dialog when the
 * reason is `wrong_repo`. Renders nothing when the team has no GitHub integration, since there
 * is no candidate list to pick from; the dismissal is still recorded without a correction.
 */
export function DismissCorrectedRepoField(): JSX.Element | null {
    const { githubIntegrations } = useValues(integrationsLogic)
    // The team's first GitHub integration, mirroring the backend's selection-source resolution.
    // Teams with several installations see the first one's repositories only, which covers the
    // dominant single-installation case without one search logic per installation in a dialog.
    const integrationId = githubIntegrations[0]?.id
    if (integrationId == null) {
        return null
    }
    return <CorrectedRepoPicker integrationId={integrationId} />
}

function CorrectedRepoPicker({ integrationId }: { integrationId: number }): JSX.Element {
    const logic = githubRepositorySearchLogic({ id: integrationId })
    const { repositoryNames, loading } = useValues(logic)
    const { setSearchQuery } = useActions(logic)

    return (
        <LemonField
            name="correctedRepository"
            label="Which repository should it have been?"
            info="Optional. The agent uses your correction when picking repositories in the future."
        >
            {({ value, onChange }) => (
                <LemonInputSelect
                    mode="single"
                    value={value ? [value] : []}
                    onChange={(newValues) => onChange(newValues[0] ?? null)}
                    options={repositoryNames.map((name) => ({ key: name.toLowerCase(), label: name }))}
                    onInputChange={setSearchQuery}
                    loading={loading}
                    placeholder="Search repositories"
                    data-attr="inbox-dismiss-corrected-repository"
                />
            )}
        </LemonField>
    )
}
