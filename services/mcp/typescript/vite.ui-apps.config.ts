import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { viteSingleFile } from 'vite-plugin-singlefile'

export default defineConfig({
    plugins: [react(), viteSingleFile()],
    build: {
        outDir: 'ui-apps-dist',
        rollupOptions: {
            input: 'src/ui-apps/app/index.html',
        },
    },
})
