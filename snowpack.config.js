module.exports = {
    alias: {
        lib: './frontend/src/lib',
        scenes: './frontend/src/scenes',
        '~': './frontend/src',
        types: './frontend/types',
        node_modules: './node_modules',
        'rrweb/typings': './node_modules/rrweb/typings',
        'funnel-graph-js': './node_modules/funnel-graph-js/index.js',
    },
    mount: {
        'frontend/public': '/',
        'frontend/src': '/_dist_',
    },
    plugins: [
        '@snowpack/plugin-react-refresh',
        '@snowpack/plugin-dotenv',
        '@snowpack/plugin-babel',
        '@snowpack/plugin-sass',
    ],
    install: ['@babel/runtime/helpers/extends', 'antd/es/layout', 'antd/es/layout/style/css'],
}
