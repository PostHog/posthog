// Fixture: mimics a destination template that pins a Google Ads version inline in the URL.
export const template = {
    hog: `
let res := fetch(f'https://googleads.googleapis.com/v21/customers/{customerId}:uploadClickConversions', {})
`,
}
