// NOTE: We do not actually use Tailwind but having this file allows
// Tailwind-supporting IDEs to autocomplete classnames, most of which we follow by convention
module.exports = {
    content: ['./frontend/**/*.{js,jsx,ts,tsx}'],
    theme: {
        extend: {
            screens: {
                sm: '576px',
                md: '768px',
                lg: '992px',
                xl: '1200px',
                xxl: '1600px',
            },
        },
    },
    plugins: [],
}
