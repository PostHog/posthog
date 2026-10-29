const { getDefaultConfig } = require('expo/metro-config')

const config = getDefaultConfig(__dirname)
config.transformer.babelTransformerPath = require.resolve('./metro.transformer.js')
module.exports = config
