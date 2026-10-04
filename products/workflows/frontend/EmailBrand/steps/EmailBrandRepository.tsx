import { useActions, useValues } from 'kea'

import { LemonButton, LemonLabel, LemonTag } from '@posthog/lemon-ui'

import { GitHubRepositoryPicker } from 'lib/integrations/GitHubIntegrationHelpers'

import { emailBrandFlowLogic } from '../emailBrandFlowLogic'
import type { EmailBrandFlowProps } from '../emailBrandFlowLogic'

const reasons = {
    name_match: 'Matches your project name',
    recent_push: 'Recently updated',
    web_language: 'Uses a web language',
}

export function EmailBrandRepository(props: EmailBrandFlowProps): JSX.Element {
    const logic = emailBrandFlowLogic(props)
    const { repository, integrationId, suggestions, busy } = useValues(logic)
    const { setRepository, detect } = useActions(logic)
    const selected = suggestions?.repositories.find((repo) => repo.full_name.toLowerCase() === repository.toLowerCase())
    return (
        <div className="max-w-lg mx-auto py-8 space-y-4">
            <div className="text-center">
                <h2>Which repository holds your app?</h2>
                <p>We suggest the closest match. Choose another repository if your brand lives elsewhere.</p>
            </div>
            <LemonLabel>Repository</LemonLabel>
            {integrationId && (
                <GitHubRepositoryPicker
                    integrationId={integrationId}
                    value={repository}
                    onChange={setRepository}
                    valueKey="full_name"
                />
            )}
            <div className="flex flex-wrap gap-2">
                {selected?.reasons.map((reason) => (
                    <LemonTag key={reason}>{reasons[reason]}</LemonTag>
                ))}
            </div>
            <LemonButton
                type="primary"
                onClick={() => detect()}
                loading={busy}
                disabledReason={!repository ? 'Choose a repository first' : undefined}
                center
                fullWidth
                data-attr="email-brand-detect"
            >
                Detect my brand
            </LemonButton>
        </div>
    )
}
