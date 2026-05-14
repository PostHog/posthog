/**
 * Shared Prettier base config for services/agent-*.
 *
 * Mirrors nodejs/.prettierrc verbatim — keeping the agent runtime services
 * formatted identically to the legacy plugin-server reduces context-switch
 * friction when contributors move between the two trees.
 */
module.exports = {
    trailingComma: 'es5',
    tabWidth: 4,
    semi: false,
    singleQuote: true,
    printWidth: 120,
    plugins: ['@trivago/prettier-plugin-sort-imports'],
    importOrder: [
        '\\.mocks?$',
        '\\.spy$',
        '<THIRD_PARTY_MODULES>',
        '^@posthog.*$',
        '^~/(.*)$',
        '^@/(.*)$',
        '^public/(.*)$',
        '^\\.+/',
    ],
    importOrderSeparation: true,
    importOrderSortSpecifiers: true,
    importOrderParserPlugins: ['typescript', 'jsx', 'classProperties', 'decorators-legacy'],
    proseWrap: 'preserve',
    overrides: [
        {
            files: ['*.md', '*.mdx'],
            options: { tabWidth: 2 },
        },
    ],
}
