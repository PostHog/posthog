/** @type {import('tailwindcss').Config} */
const config = {
    content: ['./frontend/src/**/*.{ts,tsx}', './ee/frontend/**/*.{ts,tsx}', './frontend/src/index.html'],
    important: true, // Basically this: https://sebastiandedeyne.com/why-we-use-important-with-tailwind
    theme: {
        colors: {
            // TODO: Move all colors over to Tailwind
            // Currently color utility classes are still generated with SCSS in colors.scss due to relying on our color
            // CSS vars in lots of stylesheets

            purple: '#B62AD9',
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
        screens: {
            // Sync with vars.scss
            sm: '576px',
            md: '768px',
            lg: '992px',
            xl: '1200px',
            '2xl': '1600px',
        },
        borderRadius: {
            none: '0',
            sm: '0.25rem', // Originally 0.125rem, but we're rounder
            DEFAULT: '0.375rem', // Originally 0.25rem, but we're rounder - aligned with var(--radius)
            lg: '0.5rem',
            full: '9999px',
        },
        extend: {
            fontSize: {
                xxs: ['0.625rem', '0.75rem'], // 10px (12px of line height)
            },
            spacing: {
                // Some additional larger widths for compatibility with our pre-Tailwind system
                // Don't add new ones here, in new code just use the `w-[32rem]` style for arbitrary values
                13: '3.25rem',
                15: '3.75rem',
                18: '4.5rem',
                // All whole number values up to 18 ensured above
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
                // All whole number values divisible by 20 up to 200 ensured above
                248: '62rem',
                300: '75rem',
            },
            rotate: {
                270: '270deg',
            },
            minWidth: {
                '1/3': '33.333333%',
            },
            maxWidth: {
                '1/2': '50%',
            },
            boxShadow: {
                DEFAULT: 'var(--shadow-elevation-3000)',
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
