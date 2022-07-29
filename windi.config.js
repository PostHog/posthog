import { defineConfig } from 'windicss/helpers'

export default defineConfig({
    extract: {
        include: ['./frontend/**/*.{js,jsx,ts,tsx}'],
    },
    theme: {
        extend: {
            screens: {
                sm: '576px',
                md: '768px',
                lg: '992px',
                xl: '1200px',
                xxl: '1600px',
            },
            // colors: {
            //     blue: colors.sky,
            //     red: colors.rose,
            //     pink: colors.fuchsia,
            // },
            // fontFamily: {
            //     sans: ['Graphik', 'sans-serif'],
            //     serif: ['Merriweather', 'serif'],
            // },
            // spacing: {
            //     128: '32rem',
            //     144: '36rem',
            // },
            // borderRadius: {
            //     '4xl': '2rem',
            // },
        },
    },
})
