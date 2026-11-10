/** @type {import('jest').Config} */
module.exports = {
    preset: 'jest-expo',
    resolver: 'react-native-reanimated/jest/resolver',
    setupFiles: ['<rootDir>/jest.setup.ts'],
    moduleNameMapper: {
        '^@/(.*)$': '<rootDir>/src/$1',
    },
    testPathIgnorePatterns: ['/node_modules/', '/ios/', '/android/', '/dist/'],
}
