import { useActions, useValues } from 'kea'

import { IconGithub } from '@posthog/icons'
import { LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { codeEmailLogic } from './codeEmailLogic'

export function DetectedSourceTag(): JSX.Element | null {
    const { codeEmail, sourceDetectionEnabled, sourceFormOpen, editDisabledReason } = useValues(codeEmailLogic)
    const { setSourceFormOpen } = useActions(codeEmailLogic)
    if (!sourceDetectionEnabled || codeEmail?.source_origin !== 'detected') {
        return null
    }
    return (
        <>
            <Tooltip title="PostHog found this file by searching your GitHub repos for the key.">
                <LemonTag type="muted" icon={<IconGithub />}>
                    Detected from GitHub
                </LemonTag>
            </Tooltip>
            <LemonButton
                size="xsmall"
                type="tertiary"
                onClick={() => setSourceFormOpen(!sourceFormOpen)}
                disabledReason={editDisabledReason ?? undefined}
                data-attr="code-email-change-detected-source-file"
            >
                Change
            </LemonButton>
        </>
    )
}
