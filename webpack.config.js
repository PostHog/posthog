/* global require, module, process, __dirname */
const path = require('path')
const MiniCssExtractPlugin = require('mini-css-extract-plugin')
const HtmlWebpackPlugin = require('html-webpack-plugin')
const HtmlWebpackHarddiskPlugin = require('html-webpack-harddisk-plugin')

const webpackDevServerHost = process.env.WEBPACK_HOT_RELOAD_HOST || '127.0.0.1'

module.exports = {
    mode: process.env.NODE_ENV === 'production' ? 'production' : 'development',
    devtool: process.env.NODE_ENV === 'production' ? 'source-map' : 'inline-source-map',
    entry: {
        main: './frontend/src/index.js',
        editor: './frontend/src/editor/index.js',
    },
    watchOptions: {
        ignored: /node_modules/,
    },
    output: {
        path: path.resolve(__dirname, 'frontend', 'dist'),
        filename: '[name].[hash].js',
        chunkFilename: '[name].[contenthash].js',
        publicPath: process.env.NODE_ENV === 'production' ? '/static/' : `http://${webpackDevServerHost}:8234/static/`,
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
                    {
                        // After all CSS loaders we use plugin to do his work.
                        // It gets all transformed CSS and extracts it into separate
                        // single bundled file
                        loader: MiniCssExtractPlugin.loader,
                    },
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
                ],
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
        headers: {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': '*',
        },
    },
    plugins: [
        new MiniCssExtractPlugin({
            filename: '[name].[contenthash].css',
        }),
        new HtmlWebpackPlugin({
            alwaysWriteToDisk: true,
            title: 'PostHog',
            chunks: ['main'],
            template: path.join(__dirname, 'frontend', 'src', 'index.html'),
        }),
        new HtmlWebpackPlugin({
            alwaysWriteToDisk: true,
            title: 'PostHog',
            filename: 'layout.html',
            chunks: ['main'],
            inject: false,
            template: path.join(__dirname, 'frontend', 'src', 'layout.ejs'),
        }),
        new HtmlWebpackHarddiskPlugin(),
    ],
}
