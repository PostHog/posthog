/**
 * Shared ESLint base config for services/agent-*.
 *
 * Mirrors nodejs/.eslintrc.js so the agent runtime services hold the same line
 * as the legacy plugin-server, minus rules that depend on nodejs-only paths
 * (e.g. the `~/utils/request` fetch ban).
 *
 * Consumers extend this from their own `.eslintrc.cjs` and add:
 *   - `root: true`
 *   - `parserOptions.tsconfigRootDir` (their own __dirname)
 *   - any package-specific `no-restricted-imports` patterns
 */
module.exports = {
    parser: '@typescript-eslint/parser',
    parserOptions: {
        sourceType: 'module',
        project: ['./tsconfig.eslint.json'],
    },
    plugins: ['@typescript-eslint', 'no-only-tests'],
    extends: [
        'plugin:@typescript-eslint/recommended',
        'plugin:@eslint-community/eslint-comments/recommended',
        'prettier',
    ],
    ignorePatterns: ['bin', 'dist', 'node_modules', 'migrations', '*.js', '*.cjs'],
    rules: {
        'no-only-tests/no-only-tests': 'error',
        'no-constant-binary-expression': 'error',
        'no-unused-vars': 'off',
        '@typescript-eslint/no-unused-vars': [
            'error',
            {
                ignoreRestSiblings: true,
                argsIgnorePattern: '^_',
                varsIgnorePattern: '^_',
            },
        ],
        '@typescript-eslint/explicit-function-return-type': 'off',
        '@typescript-eslint/no-non-null-assertion': 'off',
        '@typescript-eslint/no-require-imports': 'off',
        '@typescript-eslint/no-explicit-any': 'off',
        'require-await': 'off',
        '@typescript-eslint/require-await': 'error',
        '@typescript-eslint/await-thenable': 'error',
        '@typescript-eslint/no-floating-promises': 'error',
        '@typescript-eslint/no-misused-promises': ['error', { checksVoidReturn: false }],
        '@typescript-eslint/no-empty-object-type': ['error', { allowInterfaces: 'with-single-extends' }],
        curly: 'error',
        'no-fallthrough': 'warn',
    },
    overrides: [
        {
            files: ['**/*.test.ts'],
            rules: {
                '@typescript-eslint/no-explicit-any': 'off',
                '@typescript-eslint/no-floating-promises': 'off',
                // Test fakes/mocks frequently implement async signatures without ever awaiting.
                '@typescript-eslint/require-await': 'off',
            },
        },
    ],
    reportUnusedDisableDirectives: true,
}
