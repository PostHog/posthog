/* global require, module, process, __dirname */
const path = require('path')
const MiniCssExtractPlugin = require('mini-css-extract-plugin')
const HtmlWebpackPlugin = require('html-webpack-plugin')
const HtmlWebpackHarddiskPlugin = require('html-webpack-harddisk-plugin')

const webpackDevServerHost = process.env.WEBPACK_HOT_RELOAD_HOST || '127.0.0.1'

// main = app
// toolbar = new toolbar
// editor = old toolbar
module.exports = () => [createEntry('main'), createEntry('toolbar'), createEntry('editor')]

function createEntry(entry) {
    return {
        name: entry,
        mode: process.env.NODE_ENV === 'production' ? 'production' : 'development',
        devtool: process.env.NODE_ENV === 'production' ? 'source-map' : 'inline-source-map',
        entry: {
            [entry]:
                entry === 'main'
                    ? './frontend/src/index.js'
                    : entry === 'toolbar'
                    ? './frontend/src/toolbar/index.js'
                    : entry === 'editor'
                    ? './frontend/src/editor/index.js'
                    : null,
        },
        watchOptions: {
            ignored: /node_modules/,
        },
        output: {
            path: path.resolve(__dirname, 'frontend', 'dist'),
            filename: '[name].js',
            chunkFilename: '[name].[contenthash].js',
            publicPath:
                process.env.NODE_ENV === 'production'
                    ? '/static/'
                    : process.env.IS_PORTER
                    ? `https://${process.env.PORTER_WEBPACK_HOST}/static/`
                    : `http${process.env.LOCAL_HTTPS ? 's' : ''}://${webpackDevServerHost}:8234/static/`,
        },
        resolve: {
            alias: {
                '~': path.resolve(__dirname, 'frontend', 'src'),
                lib: path.resolve(__dirname, 'frontend', 'src', 'lib'),
                scenes: path.resolve(__dirname, 'frontend', 'src', 'scenes'),
                ...(process.env.NODE_ENV !== 'production'
                    ? {
                          'react-dom': '@hot-loader/react-dom',
                      }
                    : {}),
            },
        },
        module: {
            rules: [
                {
                    test: /\.js$/,
                    exclude: /(node_modules)/,
                    use: {
                        loader: 'babel-loader',
                    },
                },
                {
                    // Apply rule for .sass, .scss or .css files
                    test: /\.(sa|sc|c)ss$/,

                    // Set loaders to transform files.
                    // Loaders are applying from right to left(!)
                    // The first loader will be applied after others
                    use: [
                        entry === 'main'
                            ? {
                                  // After all CSS loaders we use plugin to do his work.
                                  // It gets all transformed CSS and extracts it into separate
                                  // single bundled file
                                  loader: MiniCssExtractPlugin.loader,
                              }
                            : entry === 'toolbar'
                            ? {
                                  loader: 'style-loader',
                                  options: {
                                      insert: function insertAtTop(element) {
                                          // tunnel behind the shadow root
                                          if (window.__PHGTLB_ADD_STYLES__) {
                                              window.__PHGTLB_ADD_STYLES__(element)
                                          } else {
                                              if (!window.__PHGTLB_STYLES__) {
                                                  window.__PHGTLB_STYLES__ = []
                                              }
                                              window.__PHGTLB_STYLES__.push(element)
                                          }
                                      },
                                  },
                              }
                            : null,
                        {
                            // This loader resolves url() and @imports inside CSS
                            loader: 'css-loader',
                        },
                        {
                            // Then we apply postCSS fixes like autoprefixer and minifying
                            loader: 'postcss-loader',
                        },
                        {
                            // First we transform SASS to standard CSS
                            loader: 'sass-loader',
                            options: {
                                implementation: require('sass'),
                            },
                        },
                    ].filter(a => a),
                },
                {
                    // Now we apply rule for images
                    test: /\.(png|jpe?g|gif|svg)$/,
                    use: [
                        {
                            // Using file-loader for these files
                            loader: 'file-loader',

                            // In options we can set different things like format
                            // and directory to save
                            options: {
                                name: '[name].[contenthash].[ext]',
                                outputPath: 'images',
                            },
                        },
                    ],
                },
                {
                    // Apply rule for fonts files
                    test: /\.(woff|woff2|ttf|otf|eot)$/,
                    use: [
                        {
                            // Using file-loader too
                            loader: 'file-loader',
                            options: {
                                name: '[name].[contenthash].[ext]',
                                outputPath: 'fonts',
                            },
                        },
                    ],
                },
            ],
        },
        devServer: {
            contentBase: path.join(__dirname, 'frontend', 'dist'),
            hot: true,
            host: webpackDevServerHost,
            port: 8234,
            public: process.env.IS_PORTER
                ? `https://${process.env.PORTER_WEBPACK_HOST}`
                : `http${process.env.LOCAL_HTTPS ? 's' : ''}://${webpackDevServerHost}:8234`,
            allowedHosts: process.env.IS_PORTER
                ? [`${process.env.PORTER_WEBPACK_HOST}`, `${process.env.PORTER_SERVER_HOST}`]
                : [],
            headers: {
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Headers': '*',
            },
        },
        plugins:
            entry === 'main'
                ? [
                      new MiniCssExtractPlugin({
                          filename: '[name].css',
                      }),
                      new HtmlWebpackPlugin({
                          alwaysWriteToDisk: true,
                          title: 'PostHog',
                          template: path.join(__dirname, 'frontend', 'src', 'index.html'),
                      }),
                      new HtmlWebpackPlugin({
                          alwaysWriteToDisk: true,
                          title: 'PostHog',
                          filename: 'layout.html',
                          inject: false,
                          template: path.join(__dirname, 'frontend', 'src', 'layout.ejs'),
                      }),
                      new HtmlWebpackHarddiskPlugin(),
                  ]
                : [],
    }
}
