/** @type {import('jest').Config} */
module.exports = {
    preset: 'ts-jest',
    testEnvironment: 'node',
    testMatch: ['<rootDir>/src/**/*.test.ts'],
    testTimeout: 5_000,
    moduleNameMapper: {
        // @repo/ass-server is workspace-linked from agent-stack; its package.json uses
        // `exports` conditional resolution that Jest's default resolver can't follow.
        '^@repo/ass-server$': '<rootDir>/node_modules/@repo/ass-server/dist/index.cjs',
    },
    transform: {
        '^.+\\.tsx?$': ['ts-jest', { tsconfig: '<rootDir>/tsconfig.test.json' }],
    },
}
