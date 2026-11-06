COUNTRIES = "Countries"
COUNTRY_INFO = "CountryInfo"
PUBLIC_HOLIDAYS = "PublicHolidays"
NEXT_PUBLIC_HOLIDAYS = "NextPublicHolidays"

ENDPOINTS: tuple[str, ...] = (
    COUNTRIES,
    COUNTRY_INFO,
    PUBLIC_HOLIDAYS,
    NEXT_PUBLIC_HOLIDAYS,
)

# PublicHolidays and NextPublicHolidays can return two rows with the same (countryCode, date,
# name) when a holiday applies to different subdivisions under different classifications (e.g.
# Good Friday is a public holiday in some US states and an optional holiday in Texas), so the
# table-wide key is a synthetic id built from the whole row — see `_holiday_id` in nager_date.py.
PRIMARY_KEYS: dict[str, list[str]] = {
    COUNTRIES: ["countryCode"],
    COUNTRY_INFO: ["countryCode"],
    PUBLIC_HOLIDAYS: ["id"],
    NEXT_PUBLIC_HOLIDAYS: ["id"],
}

ENDPOINT_DESCRIPTIONS: dict[str, str] = {
    COUNTRIES: "Countries the Nager.Date API publishes public holiday data for.",
    COUNTRY_INFO: "Country names and region for each configured country, with bordering countries.",
    PUBLIC_HOLIDAYS: "Public holidays for each configured country, for the years the API currently supports.",
    NEXT_PUBLIC_HOLIDAYS: "The next public holidays occurring within 365 days for each configured country.",
}
