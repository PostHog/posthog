/** @type {import('tailwindcss').Config} */
const config = {
    content: ['./frontend/src/**/*.{ts,tsx}', './ee/frontend/**/*.{ts,tsx}', './frontend/src/index.html'],
    theme: {
        colors: {
            // TODO: Move all colors over to Tailwind
            // Currently color utility classes are still generated with SCSS in colors.scss due to relying on our color
            // CSS vars in lots of stylesheets
        },
        fontFamily: {
            sans: [
                '-apple-system',
                'BlinkMacSystemFont',
                'Inter',
                'Segoe UI',
                'Roboto',
                'Helvetica Neue',
                'Helvetica',
                'Arial',
                'sans-serif',
                'Apple Color Emoji',
                'Segoe UI Emoji',
                'Segoe UI Symbol',
            ],
            title: [
                'MatterSQ',
                '-apple-system',
                'BlinkMacSystemFont',
                'Inter',
                'Segoe UI',
                'Roboto',
                'Helvetica Neue',
                'Helvetica',
                'Arial',
                'sans-serif',
                'Apple Color Emoji',
                'Segoe UI Emoji',
                'Segoe UI Symbol',
            ],
            mono: ['ui-monospace', 'SFMono-Regular', 'SF Mono', 'Menlo', 'Consolas', 'Liberation Mono', 'monospace'],
        },
        extend: {
            fontSize: {
                xxs: ['0.625rem', '0.75rem'], // 10px (12px of line height)
            },
            screens: {
                // Sync with vars.scss
                sm: '576px',
                md: '768px',
                lg: '992px',
                xl: '1200px',
                '2xl': '1600px',
            },
            spacing: {
                // Some additional larger widths for compatibility with our pre-Tailwind system
                // Don't add new ones here, in new code just use the `w-[32rem]` style for arbitrary values
                18: '4.5rem',
                30: '7.5rem',
                50: '12.5rem',
                60: '15rem',
                80: '20rem',
                100: '25rem',
                120: '30rem',
                140: '35rem',
                160: '40rem',
                180: '45rem',
                192: '48rem',
                200: '50rem',
                248: '62rem',
                300: '75rem',
            },
            maxWidth: {
                '1/2': '50%'
            },
            boxShadow: {
                DEFAULT: 'var(--shadow-elevation)',
            },
            flex: {
                2: '2 2 0%',
                3: '3 3 0%',
            },
        },
    },
    plugins: [require('@tailwindcss/container-queries')],
}

module.exports = config
