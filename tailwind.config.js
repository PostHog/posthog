// NOTE: We do not actually use Tailwind but having this file allows
// Tailwind-supporting IDEs to autocomplete classnames, most of which we follow by convention

// NOTE: Currently this has to be manually synced wit ./frontend/styles/vars.scss
module.exports = {
    content: ['./frontend/public/**/*.html', './frontend/src/**/*.{jsx,tsx}'],
    theme: {
        colors: {
            // TODO: Move all colors over to Tailwind
            // Currently color utility classes are still generated with SCSS in colors.scss due to relying on our color
            // CSS vars in lots of stylesheets
        },
        extend: {
            screens: {
                // Sync with vars.scss
                sm: '576px',
                md: '768px',
                lg: '992px',
                xl: '1200px',
                '2xl': '1600px',
            },
            width: {
                // Some additional larger widths for compatibility with our pre-Tailwind system
                // Don't add new ones here, in new code just use the `w-[32rem]` style for arbitrary values
                18: '4.5rem',
                30: '7.5rem',
                50: '12.5rem',
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
        },
    },
    plugins: [require('@tailwindcss/container-queries')],
}
