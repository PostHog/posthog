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
        // Worker is the one place in the agent platform that legitimately holds
        // the Anthropic SDK + Modal control plane. We still keep `nodejs/` off
        // limits — share via @posthog/agent-core instead.
        'no-restricted-imports': [
            'error',
            {
                patterns: [
                    {
                        group: ['**/nodejs/*', '../../../nodejs/*', '@posthog/nodejs'],
                        message:
                            'agent-runner must not import from nodejs/ — cherry-pick into @posthog/agent-core instead.',
                    },
                ],
            },
        ],
    },
}
