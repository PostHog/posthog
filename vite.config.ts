// import eslintPlugin from '@nabla/vite-plugin-eslint'
import { resolve } from 'path'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import tsconfigPaths from 'vite-tsconfig-paths'

export default defineConfig(({ mode }) => ({
    root: resolve('./frontend/src'),
    base: '/static/',
    server: {
        host: 'localhost',
        port: 3000,
        open: false,
        watch: {
            usePolling: true,
            disableGlobbing: false,
        },
    },
    build: {
        outDir: resolve('./frontend/dist'),
        rollupOptions: {
            input: {
                main: resolve('./frontend/src/index.tsx'),
            },
        },
        manifest: true,
    },
    plugins: [
        tsconfigPaths({
            root: resolve('.'),
        }),
        react(),
        // ...(mode !== 'test'
        //     ? [
        //           eslintPlugin(),
        //           VitePWA({
        //               registerType: 'autoUpdate',
        //               includeAssets: [
        //                   'favicon.png',
        //                   'robots.txt',
        //                   'apple-touch-icon.png',
        //                   'icons/*.svg',
        //                   'fonts/*.woff2',
        //               ],
        //               manifest: {
        //                   theme_color: '#BD34FE',
        //                   icons: [
        //                       {
        //                           src: '/android-chrome-192x192.png',
        //                           sizes: '192x192',
        //                           type: 'image/png',
        //                           purpose: 'any maskable',
        //                       },
        //                       {
        //                           src: '/android-chrome-512x512.png',
        //                           sizes: '512x512',
        //                           type: 'image/png',
        //                       },
        //                   ],
        //               },
        //           }),
        //       ]
        //     : []),
    ],
    css: {
        preprocessorOptions: {
            less: {
                javascriptEnabled: true,
            },
        },
    },
}))
