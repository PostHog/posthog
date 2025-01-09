import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import legacy from '@vitejs/plugin-legacy'
import path from 'path'
import fs from 'fs-extra'
import autoprefixer from 'autoprefixer'
import postcssPresetEnv from 'postcss-preset-env'
import cssnano from 'cssnano'
import less from 'less'

// Custom plugin for Less processing (mimicking lessLoader)
function lessPlugin() {
    return {
        name: 'vite-plugin-less',
        transform(code, id) {
            if (id.endsWith('.less')) {
                return less.render(code, { javascriptEnabled: true }).then((result) => ({
                    code: result.css,
                    map: null,
                }))
            }
        },
    }
}

// PostCSS Plugins configuration
const postcssPlugins = [
    autoprefixer(),
    postcssPresetEnv({ stage: 0 }),
    // Minify CSS in production
    ...(process.env.NODE_ENV === 'production' ? [cssnano({ preset: 'default' })] : []),
]

export default defineConfig(({ command, mode }) => {
    const isDev = mode === 'development'

    return {
        plugins: [
            react(),
            lessPlugin(),
            // Add legacy or other plugins as needed to polyfill Node or handle globals
            legacy({
                targets: ['defaults', 'not IE 11'],
            }),
        ],
        css: {
            postcss: {
                plugins: postcssPlugins,
            },
        },
        build: {
            sourcemap: true,
            minify: !isDev,
            rollupOptions: {
                input: {
                    main: path.resolve(__dirname, 'src/index.html'),
                    exporter: path.resolve(__dirname, 'src/exporter/index.html'),
                    // Add additional entry points as needed
                },
                output: {
                    assetFileNames: 'assets/[name]-[hash].[ext]',
                    chunkFileNames: '[name]-[hash].js',
                    entryFileNames: isDev ? '[name].js' : '[name]-[hash].js',
                    // Configure publicPath and other options as necessary
                },
            },
        },
        resolve: {
            extensions: ['.ts', '.tsx', '.js', '.jsx', '.scss', '.css', '.less'],
            alias: {
                // replicate alias configurations from esbuild config if needed
            },
        },
        define: {
            global: 'globalThis',
            'process.env.NODE_ENV': isDev ? '"development"' : '"production"',
        },
        server: {
            host: process.argv.includes('--host') && process.argv.includes('0.0.0.0') ? '0.0.0.0' : 'localhost',
            port: 8234,
            cors: true,
            // Additional server configuration if needed
        },
    }
})
