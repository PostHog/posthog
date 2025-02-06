/** @type {import('tailwindcss').Config} */

const commonColors = {
    'inherit': 'inherit',
    'current': 'currentColor',
    'transparent': 'transparent',
    'accent-primary': 'var(--accent-primary)',
    'accent-primary-hover': 'var(--accent-primary-hover)',
    'accent-primary-active': 'var(--accent-primary-active)',
    'accent-primary-highlight': 'var(--accent-primary-highlight)',
    'accent-secondary': 'var(--accent-secondary)',
    'accent-secondary-hover': 'var(--accent-secondary-hover)',
    'accent-secondary-active': 'var(--accent-secondary-active)',
    'accent-secondary-highlight': 'var(--accent-secondary-highlight)',
}

const config = {
    content: [
        './frontend/src/**/*.{ts,tsx}',
        './ee/frontend/**/*.{ts,tsx}',
        './frontend/src/index.html',
        './products/**/frontend/**/*.{ts,tsx}',
        './common/**/src/**/*.{ts,tsx}',
        './common/**/frontend/**/*.{ts,tsx}',
    ],
    important: true, // Basically this: https://sebastiandedeyne.com/why-we-use-important-with-tailwind
    darkMode: ['selector', '[theme="dark"]'],
    theme: {
        colors: {
            // TODO: Move all colors over to Tailwind
            // Currently color utility classes are still generated with SCSS in colors.scss due to relying on our color
            // CSS vars in lots of stylesheets

            purple: '#B62AD9',
        },
        backgroundColor: {
            ...commonColors,
            
            'fill-primary': 'var(--bg-fill-primary)',
            'fill-secondary': 'var(--bg-fill-secondary)',
            'fill-tertiary': 'var(--bg-fill-tertiary)',
            'fill-info-secondary': 'var(--bg-fill-info-secondary)',
            'fill-info-tertiary': 'var(--bg-fill-info-tertiary)',
            'fill-warning-secondary': 'var(--bg-fill-warning-secondary)',
            'fill-warning-tertiary': 'var(--bg-fill-warning-tertiary)',
            'fill-error-secondary': 'var(--bg-fill-error-secondary)',
            'fill-error-tertiary': 'var(--bg-fill-error-tertiary)',
            'fill-success-secondary': 'var(--bg-fill-success-secondary)',
            'fill-success-tertiary': 'var(--bg-fill-success-tertiary)',
        },
        textColor: {
            ...commonColors,
            
            'primary': 'var(--text-primary)',
            'on-warning-on-fill': 'var(--text-warning-on-bg-fill)',
            'on-error-on-fill': 'var(--text-error-on-bg-fill)',
            'on-success-on-fill': 'var(--text-success-on-bg-fill)',
        },
        borderColor: {
            ...commonColors,

            'primary': 'var(--border-primary)',
            'info': 'var(--border-info)',
            'warning': 'var(--border-warning)',
            'error': 'var(--border-error)',
            'success': 'var(--border-success)',
        },
        ringColor: {
            ...commonColors,
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
            sm: 'var(--radius-sm)',
            DEFAULT: 'var(--radius)',
            lg: 'var(--radius-lg)',
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
                'scene-padding': 'var(--scene-padding)',
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
