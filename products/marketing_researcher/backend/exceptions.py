"""Marketing Researcher exceptions."""


class MarketingResearcherError(Exception):
    """Base exception for Marketing Researcher errors."""

    pass


class ExaConfigurationError(MarketingResearcherError):
    """Raised when Exa.ai is not properly configured."""

    pass


class ExaAPIError(MarketingResearcherError):
    """Raised when Exa.ai API returns an error."""

    pass


class ExaValidationError(MarketingResearcherError):
    """Raised when input validation fails."""

    pass
