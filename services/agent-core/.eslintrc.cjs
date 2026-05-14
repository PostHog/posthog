const base = require('./eslint.config.base.cjs')

module.exports = {
    ...base,
    root: true,
    parserOptions: {
        ...base.parserOptions,
        tsconfigRootDir: __dirname,
    },
}
