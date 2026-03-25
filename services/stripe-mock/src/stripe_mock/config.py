from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    port: int = 12111
    scenario: str = "revenue_analytics"
    debug: bool = True

    model_config = SettingsConfigDict(env_prefix="STRIPE_MOCK_")


settings = Settings()
