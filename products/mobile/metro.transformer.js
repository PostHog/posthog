const path = require('node:path')

const upstream = require(
    require.resolve('@expo/metro-config/babel-transformer', {
        paths: [path.dirname(require.resolve('expo/package.json'))],
    })
)

// The WebView gets mermaid's browser bundle and the replay player as text. Exporting them as strings
// keeps Hermes from running a DOM library and keeps them out of startup until a WebView requires one.
const RAW_MODULES = [
    path.join('mermaid', 'dist', 'mermaid.min.js'),
    path.join('src', 'features', 'replay', 'web', 'phonePlayer.generated.replay'),
]

module.exports = {
    ...upstream,
    transform(props) {
        if (RAW_MODULES.some((suffix) => props.filename.endsWith(suffix))) {
            return upstream.transform({
                ...props,
                src: `module.exports = ${JSON.stringify(props.src)};`,
            })
        }
        return upstream.transform(props)
    },
}
