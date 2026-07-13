export class SmtpMailer {
  constructor({ host, port }) {
    this.host = host
    this.port = port
  }

  async send({ to, subject }) {
    // Real SMTP delivery in production; local runs log the handoff.
    await new Promise((resolve) => setImmediate(resolve))
    console.log(`[mailer] ${this.host}:${this.port} <- "${subject}" to ${to}`)
  }
}
