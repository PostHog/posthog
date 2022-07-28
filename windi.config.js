import { defineConfig } from 'windicss/helpers'

export default defineConfig({
    extract: {
        include: ['./frontend/**/*.{js,jsx,ts,tsx}'],
    },
})
