/** @type {import('tailwindcss').Config} */
module.exports = {
    content: ['./frontend/src/**/*.tsx', './frontend/src/index.html'], // Avoiding analysis of .ts files for performance
    theme: {
        colors: {
            // TODO: Move all colors over to Tailwind
            // Currently color utility classes are still generated with SCSS in colors.scss due to relying on our color
            // CSS vars in lots of stylesheets
        },
        fontFamily: {
          // TODO
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
