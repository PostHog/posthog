// Fixture: mimics a destination template that pins a Meta Graph version via a default variable.
export const template = {
    hog: `
let apiVersion := empty(inputs.api_version) ? 'v21.0' : inputs.api_version
let url := f'https://graph.facebook.com/{apiVersion}/{phoneNumberId}/messages'
`,
}
