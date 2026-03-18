/** @type {import('tailwindcss').Config} */
module.exports = {
    content: [
        './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
        './src/components/**/*.{js,ts,jsx,tsx,mdx}',
        './src/app/**/*.{js,ts,jsx,tsx,mdx}',
    ],
    theme: {
        extend: {
            boxShadow: {
                sm: '0 1px 2px 0 rgba(0, 0, 0, 0.05), 0 1px 3px 0 rgba(0, 0, 0, 0.1), 0 0 0 1px rgba(0, 0, 0, 0.05)',
                DEFAULT:
                    '0 2px 4px -1px rgba(0, 0, 0, 0.06), 0 4px 8px -1px rgba(0, 0, 0, 0.1), 0 0 0 1px rgba(0, 0, 0, 0.04), 0 8px 16px -4px rgba(0, 0, 0, 0.08)',
                md: '0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06), 0 0 0 1px rgba(0, 0, 0, 0.05), 0 10px 15px -3px rgba(0, 0, 0, 0.1)',
                lg: '0 4px 8px -2px rgba(0, 0, 0, 0.08), 0 8px 16px -4px rgba(0, 0, 0, 0.12), 0 16px 32px -8px rgba(0, 0, 0, 0.1), 0 0 0 1px rgba(0, 0, 0, 0.04), 0 2px 4px -1px rgba(0, 0, 0, 0.06)',
            },
        },
    },
    plugins: [require('daisyui')],
    daisyui: {
        themes: [
            {
                hedgebox: {
                    primary: '#0f0f23',
                    'primary-content': '#ffffff',
                    secondary: '#6b7280',
                    'secondary-content': '#ffffff',
                    accent: '#2563eb',
                    'accent-content': '#ffffff',
                    neutral: '#1f2937',
                    'neutral-content': '#f9fafb',
                    'base-100': '#ffffff',
                    'base-200': '#f8fafc',
                    'base-300': '#e2e8f0',
                    'base-content': '#0f172a',
                    info: '#0ea5e9',
                    'info-content': '#ffffff',
                    success: '#10b981',
                    'success-content': '#ffffff',
                    warning: '#f59e0b',
                    'warning-content': '#ffffff',
                    error: '#ef4444',
                    'error-content': '#ffffff',
                },
            },
        ],
    },
}
