from products.messaging.backend.provider_imports.base import ImportProvider
from products.messaging.backend.provider_imports.customerio import CustomerIOImportProvider

# Add a provider here, and its key to ImportProviderKey, to make it importable.
PROVIDERS: dict[str, ImportProvider] = {provider.key: provider for provider in (CustomerIOImportProvider(),)}


class UnknownImportProvider(Exception):
    pass


def get_provider(key: str) -> ImportProvider:
    provider = PROVIDERS.get(key)
    if provider is None:
        raise UnknownImportProvider(key)
    return provider
