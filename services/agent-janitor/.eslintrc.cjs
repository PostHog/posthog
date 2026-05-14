const base = require('../agent-core/eslint.config.base.cjs')

module.exports = {
    ...base,
    root: true,
    parserOptions: {
        ...base.parserOptions,
        tsconfigRootDir: __dirname,
    },
    rules: {
        ...base.rules,
        // Same blast-radius rule as ingress — janitor is operational, not a session executor.
        // Anything that touches the SDK belongs in agent-runner.
        'no-restricted-imports': [
            'error',
            {
                patterns: [
                    {
                        group: ['@anthropic-ai/*', '@modal/*', 'modal', 'claude-agent-sdk'],
                        message:
                            'agent-janitor must not import the Claude Agent SDK or Modal — those belong to agent-runner.',
                    },
                    {
                        group: ['**/nodejs/*', '../../../nodejs/*', '@posthog/nodejs'],
                        message:
                            'agent-janitor must not import from nodejs/ — cherry-pick into @posthog/agent-core instead.',
                    },
                ],
            },
        ],
    },
}
