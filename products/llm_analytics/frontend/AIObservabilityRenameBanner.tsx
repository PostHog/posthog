import { useActions } from 'kea'

import { LemonBanner, Link } from '@posthog/lemon-ui'

import { supportLogic } from 'lib/components/Support/supportLogic'

export function AIObservabilityRenameBanner(): JSX.Element {
    const { openSupportForm } = useActions(supportLogic)

    return (
        <LemonBanner type="info" dismissKey="ai-observability-renamed-from-llm-analytics">
            AI observability was previously called LLM analytics. If anything looks off after the rename,{' '}
            <Link onClick={() => openSupportForm({ kind: 'support', target_area: 'llm-analytics' })}>contact us</Link>.
        </LemonBanner>
    )
}
