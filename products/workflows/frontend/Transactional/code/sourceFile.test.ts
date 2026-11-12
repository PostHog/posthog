import { parseSourceFile } from './sourceFile'

describe('sourceFile', () => {
    it.each([
        [
            'a GitHub file',
            'https://github.com/acme/web/blob/main/src/emails/password-reset.tsx',
            { host: 'github', repo: 'acme/web', path: 'src/emails/password-reset.tsx' },
        ],
        [
            'a GitHub file with a line anchor',
            'https://github.com/acme/web/blob/main/src/emails/receipt.tsx?plain=1#L12',
            { host: 'github', repo: 'acme/web', path: 'src/emails/receipt.tsx' },
        ],
        [
            'a GitLab file in a nested group',
            'https://gitlab.com/acme/shop/fulfilment/-/blob/4f2c9e1a7b/app/mailers/order_shipped.rb',
            { host: 'gitlab', repo: 'acme/shop/fulfilment', path: 'app/mailers/order_shipped.rb' },
        ],
        [
            'a GitHub file whose name has a stray percent sign',
            'https://github.com/acme/web/blob/main/src/emails/100%.tsx',
            { host: 'github', repo: 'acme/web', path: 'src/emails/100%.tsx' },
        ],
        [
            'a GitLab file with a broken escape',
            'https://gitlab.com/acme/web/-/blob/release%ZZ/src/a%ZZ.ts',
            { host: 'gitlab', repo: 'acme/web', path: 'src/a%ZZ.ts' },
        ],
        [
            'a file on another host',
            'https://git.example.com/billing/emails/invoice_paid.py',
            { host: 'other', repo: '', path: 'git.example.com/billing/emails/invoice_paid.py' },
        ],
        [
            'a GitHub link that is not a file',
            'https://github.com/acme/web',
            { host: 'other', repo: '', path: 'github.com/acme/web' },
        ],
    ])('reads %s', (_name, url, expected) => {
        expect(parseSourceFile(url)).toEqual({ url, ...expected })
    })
})
