const { getDefaultConfig } = require('expo/metro-config')

const config = getDefaultConfig(__dirname)
config.resolver.sourceExts.push('replay')
config.transformer.babelTransformerPath = require.resolve('./metro.transformer.js')
module.exports = config
