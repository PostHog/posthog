const fs = require('fs')
const path = require('path')

const cwd = process.cwd()
const isTS = fs.existsSync(path.join(cwd, 'tsconfig.json'))

module.exports = {
    exclude: ['**/*.stories.*', '**/*.test.*', 'frontend/src/test'],
    mount: {
        'frontend/public': { url: '/', static: true },
        'frontend/src': { url: '/dist' },
    },
    plugins: [
        '@snowpack/plugin-react-refresh',
        '@snowpack/plugin-babel',
        '@snowpack/plugin-dotenv',
        ...(isTS ? ['@snowpack/plugin-typescript'] : []),
    ],
    devOptions: {},
    packageOptions: {},
}
