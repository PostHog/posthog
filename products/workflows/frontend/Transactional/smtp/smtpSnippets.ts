import { Language } from 'lib/components/CodeSnippet'

export type SmtpSnippetKey = 'env' | 'nodemailer' | 'django' | 'laravel'

export const SMTP_SNIPPETS: Record<
    SmtpSnippetKey,
    { language: Language; code: (host: string, key: string) => string }
> = {
    env: {
        language: Language.Bash,
        code: (host, key) =>
            `SMTP_HOST=${host}\nSMTP_PORT=465\nSMTP_SECURE=true\nSMTP_USER=posthog\nSMTP_PASSWORD=${key}`,
    },
    nodemailer: {
        language: Language.JavaScript,
        code: (host, key) => `const transport = nodemailer.createTransport({
    host: '${host}',
    port: 465,
    secure: true,
    auth: { user: 'posthog', pass: '${key}' },
})`,
    },
    django: {
        language: Language.Python,
        code: (host, key) => `EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = "${host}"
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = "posthog"
EMAIL_HOST_PASSWORD = "${key}"`,
    },
    laravel: {
        language: Language.Bash,
        code: (host, key) => `MAIL_MAILER=smtp
MAIL_HOST=${host}
MAIL_PORT=587
MAIL_ENCRYPTION=tls
MAIL_USERNAME=posthog
MAIL_PASSWORD=${key}`,
    },
}
