// Fixture: mimics the real Google Ads destination — versioned URL whose endpoint name follows a
// Hog interpolation containing nested quotes (the brace-aware scanner regression case).
export const template = {
    inputs_schema: [
        {
            key: 'customerId',
            description: 'See https://support.google.com/google-ads/answer/7012522 and https://posthog.com/docs/cdp',
        },
    ],
    hog: `
let res := fetch(f'https://googleads.googleapis.com/v21/customers/{splitByString('/', inputs.customerId)[1]}:uploadClickConversions', {})
`,
}
