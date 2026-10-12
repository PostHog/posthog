from products.workflows.backend.facade.contracts import EmailDomainVerification
from products.workflows.backend.providers.ses import SESProvider


def get_ses_email_domain_verification(
    domain: str, *, mail_from_subdomain: str, team_id: int
) -> EmailDomainVerification:
    return SESProvider().get_email_domain_verification(domain, mail_from_subdomain, team_id)
