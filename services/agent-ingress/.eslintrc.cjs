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
        // Blast-radius rule: agent-ingress must not pull in the Claude Agent SDK,
        // Modal, or any nodejs/ legacy plugin-server primitives. Cherry-pick into
        // @posthog/agent-core if you need something from those trees.
        'no-restricted-imports': [
            'error',
            {
                patterns: [
                    {
                        group: ['@anthropic-ai/*', '@modal/*', 'modal', 'claude-agent-sdk'],
                        message:
                            'agent-ingress must not import the Claude Agent SDK or Modal — those belong to agent-runner. Blast-radius rule.',
                    },
                    {
                        group: ['**/nodejs/*', '../../../nodejs/*', '@posthog/nodejs'],
                        message:
                            'agent-ingress must not import from nodejs/ — cherry-pick into @posthog/agent-core instead.',
                    },
                ],
            },
        ],
    },
}
