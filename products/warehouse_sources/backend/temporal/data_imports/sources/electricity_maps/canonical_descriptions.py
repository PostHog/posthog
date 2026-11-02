"""Canonical, documentation-sourced descriptions for Electricity Maps endpoints and columns.

Sourced from the official Electricity Maps API reference (https://app.electricitymaps.com/docs/api).
Keyed by the endpoint names in `settings.py` `ENDPOINTS`, which match the `ExternalDataSchema.name`
of a synced Electricity Maps table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "carbon_intensity": {
        "description": "Hourly carbon intensity of electricity consumed in a zone, in grams of "
        "CO2 equivalent per kilowatt-hour (gCO2eq/kWh).",
        "docs_url": "https://app.electricitymaps.com/docs/api",
        "columns": {
            "zone": "Identifier of the electricity grid zone, e.g. `DE` or `DK-DK1`.",
            "carbonIntensity": "Carbon intensity of consumed electricity for this hour, in gCO2eq/kWh.",
            "datetime": "UTC start of the hour this measurement covers.",
            "updatedAt": "When Electricity Maps last updated this data point.",
            "createdAt": "When Electricity Maps first created this data point.",
            "emissionFactorType": "Type of emission factors used to compute the intensity: `lifecycle` or `direct`.",
            "isEstimated": "Whether this value is an estimate rather than measured data.",
            "estimationMethod": "Model used to produce the estimate, or null for measured data.",
        },
    },
    "power_breakdown": {
        "description": "Hourly origin of electricity in a zone: production, consumption, import and "
        "export flows broken down by source, in megawatts (MW).",
        "docs_url": "https://app.electricitymaps.com/docs/api",
        "columns": {
            "zone": "Identifier of the electricity grid zone, e.g. `DE` or `DK-DK1`.",
            "datetime": "UTC start of the hour this measurement covers.",
            "updatedAt": "When Electricity Maps last updated this data point.",
            "createdAt": "When Electricity Maps first created this data point.",
            "powerConsumptionBreakdown": "Electricity consumed in the zone by production type (nuclear, wind, solar, ...), in MW, after imports and exports.",
            "powerProductionBreakdown": "Electricity produced in the zone by production type, in MW.",
            "powerImportBreakdown": "Physical electricity imports at the zone border, by neighbouring zone, in MW.",
            "powerExportBreakdown": "Physical electricity exports at the zone border, by neighbouring zone, in MW.",
            "fossilFreePercentage": "Share of consumed power from fossil-free sources (renewables and nuclear), in percent.",
            "renewablePercentage": "Share of consumed power from renewable sources, in percent.",
            "powerConsumptionTotal": "Total power consumed in the zone, in MW.",
            "powerProductionTotal": "Total power produced in the zone, in MW.",
            "powerImportTotal": "Total power imported into the zone, in MW.",
            "powerExportTotal": "Total power exported from the zone, in MW.",
            "isEstimated": "Whether this value is an estimate rather than measured data.",
            "estimationMethod": "Model used to produce the estimate, or null for measured data.",
        },
    },
    "price_day_ahead": {
        "description": "Hourly day-ahead electricity market price in a zone, in the currency and unit "
        "given on each row (for example EUR/MWh).",
        "docs_url": "https://app.electricitymaps.com/docs/api",
        "columns": {
            "zone": "Identifier of the electricity grid zone, e.g. `DE` or `DK-DK1`.",
            "datetime": "UTC start of the hour this price applies to.",
            "updatedAt": "When Electricity Maps last updated this data point.",
            "createdAt": "When Electricity Maps first created this data point.",
            "value": "Day-ahead price for this hour, in the currency and unit given by `unit`.",
            "unit": "Currency and unit of the price, e.g. `EUR/MWh`.",
            "source": "Where Electricity Maps obtained the price.",
            "temporalGranularity": "Time resolution of the data point, e.g. `hourly`.",
        },
    },
    "locational_marginal_price_day_ahead": {
        "description": "Hourly day-ahead locational marginal price (LMP) at a United States pricing node, "
        "with its energy, congestion, loss and greenhouse gas components.",
        "docs_url": "https://app.electricitymaps.com/docs/api",
        "columns": {
            "entityName": "Pricing node identifier, e.g. `CORTINA_1_N106`.",
            "entityType": "Type of the priced entity, e.g. `PNODE`.",
            "datetime": "UTC start of the hour this price applies to.",
            "updatedAt": "When Electricity Maps last updated this data point.",
            "createdAt": "When Electricity Maps first created this data point.",
            "lmp": "Locational marginal price for this hour, in the currency and unit given by `unit`.",
            "unit": "Currency and unit of the price, e.g. `USD/MWh`.",
            "energy": "Energy component of the locational marginal price.",
            "congestion": "Congestion component of the locational marginal price.",
            "loss": "Loss component of the locational marginal price.",
            "greenhouseGas": "Greenhouse gas component of the locational marginal price.",
            "source": "Where Electricity Maps obtained the price.",
            "temporalGranularity": "Time resolution of the data point, e.g. `hourly`.",
        },
    },
    "carbon_intensity_forecast": {
        "description": "Latest hourly carbon intensity forecast for a zone, in gCO2eq/kWh. Each sync "
        "replaces the table with the forecast Electricity Maps has most recently published.",
        "docs_url": "https://app.electricitymaps.com/docs/api",
        "columns": {
            "zone": "Identifier of the electricity grid zone, e.g. `DE` or `DK-DK1`.",
            "datetime": "UTC start of the future hour this forecast applies to.",
            "carbonIntensity": "Forecasted carbon intensity of consumed electricity for this hour, in gCO2eq/kWh.",
            "updatedAt": "When Electricity Maps last updated the forecast.",
        },
    },
    "zones": {
        "description": "Electricity Maps zones, with names, countries and parent zones, for resolving "
        "the zone identifiers on other Electricity Maps tables.",
        "docs_url": "https://app.electricitymaps.com/docs/api",
        "columns": {
            "zoneKey": "Identifier of the electricity grid zone, e.g. `DK-DK2`.",
            "zoneName": "Human-readable zone name.",
            "displayName": "Display name for the zone.",
            "countryCode": "ISO country code of the zone.",
            "countryName": "Country name of the zone.",
            "zoneParentKey": "Key of the parent zone when this zone is a subzone, otherwise null.",
            "subZoneKeys": "Keys of the subzones of this zone.",
            "isCommerciallyAvailable": "Whether the zone is commercially available.",
            "tier": "Data tier of the zone.",
            "access": "Endpoints that the API token can reach for this zone.",
        },
    },
}
