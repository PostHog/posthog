import { useActions, useValues } from 'kea'

import { LemonInput, LemonTabs } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { tracingOtlpSetupLogic } from './tracingOtlpSetupLogic'
import { TRACING_SETUP_PLATFORMS } from './tracingOtlpSnippets'

export function TracingOtlpSetup(): JSX.Element {
    const { platform, environment, snippet } = useValues(tracingOtlpSetupLogic)
    const { setPlatform, setEnvironment, snippetCopied } = useActions(tracingOtlpSetupLogic)

    return (
        <div className="flex flex-col gap-2">
            <span className="text-xs text-tertiary">
                Point any OpenTelemetry SDK or collector at PostHog. Your project token is already filled in.
            </span>
            <label className="flex items-center gap-2 text-xs">
                <span className="shrink-0 font-semibold">Environment</span>
                <LemonInput
                    size="small"
                    className="max-w-60"
                    placeholder="production (optional)"
                    value={environment}
                    onChange={setEnvironment}
                    data-attr="tracing-setup-environment"
                />
            </label>
            <LemonTabs
                activeKey={platform}
                onChange={setPlatform}
                size="small"
                tabs={TRACING_SETUP_PLATFORMS.map(({ key, label }) => ({
                    key,
                    label,
                    content: (
                        <CodeSnippet
                            language={key === 'collector' || key === 'kubernetes' ? Language.YAML : Language.Bash}
                            onCopy={snippetCopied}
                        >
                            {snippet}
                        </CodeSnippet>
                    ),
                }))}
            />
            <span className="text-xs text-secondary">
                Restart your services after applying this, so the SDK picks up the new settings. This page switches to
                your traces as soon as the first span arrives.
            </span>
        </div>
    )
}
