from dataclasses import dataclass

from posthog.schema import DatabaseSchemaManagedViewTableKind

from posthog.hogql.database.models import BooleanDatabaseField, DecimalDatabaseField, FieldOrTable, StringDatabaseField


@dataclass
class Schema:
    kind: DatabaseSchemaManagedViewTableKind
    fields: dict[str, FieldOrTable]
    source_suffix: str
    events_suffix: str


FieldsDict = dict[str, FieldOrTable]

# Currency-related fields used to compute revenue
# It's used both in the charge and revenue item schemas
BASE_CURRENCY_FIELDS: FieldsDict = {
    # Mostly helper fields
    "original_currency": StringDatabaseField(name="original_currency"),
    "original_amount": DecimalDatabaseField(name="original_amount"),
    "enable_currency_aware_divider": BooleanDatabaseField(name="enable_currency_aware_divider"),
    "currency_aware_divider": DecimalDatabaseField(name="currency_aware_divider"),
    "currency_aware_amount": DecimalDatabaseField(name="currency_aware_amount"),
    # Actual two fields we care about
    "currency": StringDatabaseField(name="currency"),
    "amount": DecimalDatabaseField(name="amount"),
}
