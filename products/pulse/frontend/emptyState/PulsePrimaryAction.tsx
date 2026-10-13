import { useActions, useValues } from 'kea'

import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { BriefConfigModal } from '../BriefConfigModal'
import { pulseLogic } from '../pulseLogic'
import { RunBriefButton } from '../RunBriefButton'

/**
 * Create path for the Pulse empty state. The run button and the focus modal are what the
 * scene header offers, and the gate replaces the scene, so the empty state renders both
 * itself. The AI consent line replaces the scene's banner for the same reason.
 */
export function PulsePrimaryAction(): JSX.Element {
    const { showAiConsentBanner } = useValues(pulseLogic)
    const { openConfigModal } = useActions(pulseLogic)

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2">
                <RunBriefButton />
                <span className="text-secondary text-sm">or</span>
                <Link onClick={() => openConfigModal(null)} data-attr="pulse-empty-state-new-config">
                    set a focus first
                </Link>
            </div>
            {showAiConsentBanner && (
                <span className="text-secondary text-xs">
                    Pulse runs AI over your project data. Approve AI data processing in{' '}
                    <Link to={urls.settings('organization-details', 'organization-ai-consent')}>
                        organization settings
                    </Link>{' '}
                    to run a brief.
                </span>
            )}
            <BriefConfigModal />
        </div>
    )
}
