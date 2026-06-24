/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 10 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Retrieve a project and its settings.
 */
export const organizationsProjectsRetrievePathIdMin = -2147483648
export const organizationsProjectsRetrievePathIdMax = 2147483647

export const OrganizationsProjectsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod
        .number()
        .min(organizationsProjectsRetrievePathIdMin)
        .max(organizationsProjectsRetrievePathIdMax)
        .describe('A unique value identifying this project.'),
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to /api/organizations/."
        ),
})

/**
 * Update one or more of a project's settings. Only the fields included in the request body are changed.
 */
export const organizationsProjectsPartialUpdatePathIdMin = -2147483648
export const organizationsProjectsPartialUpdatePathIdMax = 2147483647

export const OrganizationsProjectsPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod
        .number()
        .min(organizationsProjectsPartialUpdatePathIdMin)
        .max(organizationsProjectsPartialUpdatePathIdMax)
        .describe('A unique value identifying this project.'),
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to /api/organizations/."
        ),
})

export const organizationsProjectsPartialUpdateBodyNameMax = 200

export const organizationsProjectsPartialUpdateBodyProductDescriptionMax = 1000

export const organizationsProjectsPartialUpdateBodyAppUrlsItemMax = 200

export const organizationsProjectsPartialUpdateBodyPersonDisplayNamePropertiesItemMax = 400

export const organizationsProjectsPartialUpdateBodySessionRecordingSampleRateRegExp = new RegExp(
    '^-?\\d{0,1}(?:\\.\\d{0,2})?$'
)
export const organizationsProjectsPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMin = 0
export const organizationsProjectsPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMax = 30000

export const organizationsProjectsPartialUpdateBodySessionRecordingTriggerMatchTypeConfigMax = 24

export const organizationsProjectsPartialUpdateBodyRecordingDomainsItemMax = 200

export const organizationsProjectsPartialUpdateBodyMarketingAnalyticsConfigAttributionWindowDaysMax = 90

export const organizationsProjectsPartialUpdateBodyDefaultDataThemeMin = -2147483648
export const organizationsProjectsPartialUpdateBodyDefaultDataThemeMax = 2147483647

export const OrganizationsProjectsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .min(1)
            .max(organizationsProjectsPartialUpdateBodyNameMax)
            .optional()
            .describe('Human-readable project name.'),
        product_description: zod
            .string()
            .max(organizationsProjectsPartialUpdateBodyProductDescriptionMax)
            .nullish()
            .describe(
                'Short description of what the project is about. This is helpful to give our AI agents context about your project.'
            ),
        app_urls: zod
            .array(zod.string().max(organizationsProjectsPartialUpdateBodyAppUrlsItemMax).nullable())
            .optional(),
        anonymize_ips: zod
            .boolean()
            .optional()
            .describe('When true, PostHog drops the IP address from every ingested event.'),
        completed_snippet_onboarding: zod.boolean().optional(),
        test_account_filters: zod
            .unknown()
            .optional()
            .describe('Filter groups that identify internal/test traffic to be excluded from insights.'),
        test_account_filters_default_checked: zod
            .boolean()
            .nullish()
            .describe('When true, new insights default to excluding internal/test users.'),
        path_cleaning_filters: zod
            .unknown()
            .optional()
            .describe(
                'Regex rewrite rules that collapse dynamic path segments (e.g. user IDs) before displaying URLs in paths.'
            ),
        is_demo: zod.boolean().optional(),
        timezone: zod
            .string()
            .optional()
            .describe(
                'IANA timezone used for date-based filters and reporting (e.g. `America/Los_Angeles`).\n\n* `Africa/Abidjan` - Africa/Abidjan\n* `Africa/Accra` - Africa/Accra\n* `Africa/Addis_Ababa` - Africa/Addis_Ababa\n* `Africa/Algiers` - Africa/Algiers\n* `Africa/Asmara` - Africa/Asmara\n* `Africa/Asmera` - Africa/Asmera\n* `Africa/Bamako` - Africa/Bamako\n* `Africa/Bangui` - Africa/Bangui\n* `Africa/Banjul` - Africa/Banjul\n* `Africa/Bissau` - Africa/Bissau\n* `Africa/Blantyre` - Africa/Blantyre\n* `Africa/Brazzaville` - Africa/Brazzaville\n* `Africa/Bujumbura` - Africa/Bujumbura\n* `Africa/Cairo` - Africa/Cairo\n* `Africa/Casablanca` - Africa/Casablanca\n* `Africa/Ceuta` - Africa/Ceuta\n* `Africa/Conakry` - Africa/Conakry\n* `Africa/Dakar` - Africa/Dakar\n* `Africa/Dar_es_Salaam` - Africa/Dar_es_Salaam\n* `Africa/Djibouti` - Africa/Djibouti\n* `Africa/Douala` - Africa/Douala\n* `Africa/El_Aaiun` - Africa/El_Aaiun\n* `Africa/Freetown` - Africa/Freetown\n* `Africa/Gaborone` - Africa/Gaborone\n* `Africa/Harare` - Africa/Harare\n* `Africa/Johannesburg` - Africa/Johannesburg\n* `Africa/Juba` - Africa/Juba\n* `Africa/Kampala` - Africa/Kampala\n* `Africa/Khartoum` - Africa/Khartoum\n* `Africa/Kigali` - Africa/Kigali\n* `Africa/Kinshasa` - Africa/Kinshasa\n* `Africa/Lagos` - Africa/Lagos\n* `Africa/Libreville` - Africa/Libreville\n* `Africa/Lome` - Africa/Lome\n* `Africa/Luanda` - Africa/Luanda\n* `Africa/Lubumbashi` - Africa/Lubumbashi\n* `Africa/Lusaka` - Africa/Lusaka\n* `Africa/Malabo` - Africa/Malabo\n* `Africa/Maputo` - Africa/Maputo\n* `Africa/Maseru` - Africa/Maseru\n* `Africa/Mbabane` - Africa/Mbabane\n* `Africa/Mogadishu` - Africa/Mogadishu\n* `Africa/Monrovia` - Africa/Monrovia\n* `Africa/Nairobi` - Africa/Nairobi\n* `Africa/Ndjamena` - Africa/Ndjamena\n* `Africa/Niamey` - Africa/Niamey\n* `Africa/Nouakchott` - Africa/Nouakchott\n* `Africa/Ouagadougou` - Africa/Ouagadougou\n* `Africa/Porto-Novo` - Africa/Porto-Novo\n* `Africa/Sao_Tome` - Africa/Sao_Tome\n* `Africa/Timbuktu` - Africa/Timbuktu\n* `Africa/Tripoli` - Africa/Tripoli\n* `Africa/Tunis` - Africa/Tunis\n* `Africa/Windhoek` - Africa/Windhoek\n* `America/Adak` - America/Adak\n* `America/Anchorage` - America/Anchorage\n* `America/Anguilla` - America/Anguilla\n* `America/Antigua` - America/Antigua\n* `America/Araguaina` - America/Araguaina\n* `America/Argentina/Buenos_Aires` - America/Argentina/Buenos_Aires\n* `America/Argentina/Catamarca` - America/Argentina/Catamarca\n* `America/Argentina/ComodRivadavia` - America/Argentina/ComodRivadavia\n* `America/Argentina/Cordoba` - America/Argentina/Cordoba\n* `America/Argentina/Jujuy` - America/Argentina/Jujuy\n* `America/Argentina/La_Rioja` - America/Argentina/La_Rioja\n* `America/Argentina/Mendoza` - America/Argentina/Mendoza\n* `America/Argentina/Rio_Gallegos` - America/Argentina/Rio_Gallegos\n* `America/Argentina/Salta` - America/Argentina/Salta\n* `America/Argentina/San_Juan` - America/Argentina/San_Juan\n* `America/Argentina/San_Luis` - America/Argentina/San_Luis\n* `America/Argentina/Tucuman` - America/Argentina/Tucuman\n* `America/Argentina/Ushuaia` - America/Argentina/Ushuaia\n* `America/Aruba` - America/Aruba\n* `America/Asuncion` - America/Asuncion\n* `America/Atikokan` - America/Atikokan\n* `America/Atka` - America/Atka\n* `America/Bahia` - America/Bahia\n* `America/Bahia_Banderas` - America/Bahia_Banderas\n* `America/Barbados` - America/Barbados\n* `America/Belem` - America/Belem\n* `America/Belize` - America/Belize\n* `America/Blanc-Sablon` - America/Blanc-Sablon\n* `America/Boa_Vista` - America/Boa_Vista\n* `America/Bogota` - America/Bogota\n* `America/Boise` - America/Boise\n* `America/Buenos_Aires` - America/Buenos_Aires\n* `America/Cambridge_Bay` - America/Cambridge_Bay\n* `America/Campo_Grande` - America/Campo_Grande\n* `America/Cancun` - America/Cancun\n* `America/Caracas` - America/Caracas\n* `America/Catamarca` - America/Catamarca\n* `America/Cayenne` - America/Cayenne\n* `America/Cayman` - America/Cayman\n* `America/Chicago` - America/Chicago\n* `America/Chihuahua` - America/Chihuahua\n* `America/Ciudad_Juarez` - America/Ciudad_Juarez\n* `America/Coral_Harbour` - America/Coral_Harbour\n* `America/Cordoba` - America/Cordoba\n* `America/Costa_Rica` - America/Costa_Rica\n* `America/Creston` - America/Creston\n* `America/Cuiaba` - America/Cuiaba\n* `America/Curacao` - America/Curacao\n* `America/Danmarkshavn` - America/Danmarkshavn\n* `America/Dawson` - America/Dawson\n* `America/Dawson_Creek` - America/Dawson_Creek\n* `America/Denver` - America/Denver\n* `America/Detroit` - America/Detroit\n* `America/Dominica` - America/Dominica\n* `America/Edmonton` - America/Edmonton\n* `America/Eirunepe` - America/Eirunepe\n* `America/El_Salvador` - America/El_Salvador\n* `America/Ensenada` - America/Ensenada\n* `America/Fort_Nelson` - America/Fort_Nelson\n* `America/Fort_Wayne` - America/Fort_Wayne\n* `America/Fortaleza` - America/Fortaleza\n* `America/Glace_Bay` - America/Glace_Bay\n* `America/Godthab` - America/Godthab\n* `America/Goose_Bay` - America/Goose_Bay\n* `America/Grand_Turk` - America/Grand_Turk\n* `America/Grenada` - America/Grenada\n* `America/Guadeloupe` - America/Guadeloupe\n* `America/Guatemala` - America/Guatemala\n* `America/Guayaquil` - America/Guayaquil\n* `America/Guyana` - America/Guyana\n* `America/Halifax` - America/Halifax\n* `America/Havana` - America/Havana\n* `America/Hermosillo` - America/Hermosillo\n* `America/Indiana/Indianapolis` - America/Indiana/Indianapolis\n* `America/Indiana/Knox` - America/Indiana/Knox\n* `America/Indiana/Marengo` - America/Indiana/Marengo\n* `America/Indiana/Petersburg` - America/Indiana/Petersburg\n* `America/Indiana/Tell_City` - America/Indiana/Tell_City\n* `America/Indiana/Vevay` - America/Indiana/Vevay\n* `America/Indiana/Vincennes` - America/Indiana/Vincennes\n* `America/Indiana/Winamac` - America/Indiana/Winamac\n* `America/Indianapolis` - America/Indianapolis\n* `America/Inuvik` - America/Inuvik\n* `America/Iqaluit` - America/Iqaluit\n* `America/Jamaica` - America/Jamaica\n* `America/Jujuy` - America/Jujuy\n* `America/Juneau` - America/Juneau\n* `America/Kentucky/Louisville` - America/Kentucky/Louisville\n* `America/Kentucky/Monticello` - America/Kentucky/Monticello\n* `America/Knox_IN` - America/Knox_IN\n* `America/Kralendijk` - America/Kralendijk\n* `America/La_Paz` - America/La_Paz\n* `America/Lima` - America/Lima\n* `America/Los_Angeles` - America/Los_Angeles\n* `America/Louisville` - America/Louisville\n* `America/Lower_Princes` - America/Lower_Princes\n* `America/Maceio` - America/Maceio\n* `America/Managua` - America/Managua\n* `America/Manaus` - America/Manaus\n* `America/Marigot` - America/Marigot\n* `America/Martinique` - America/Martinique\n* `America/Matamoros` - America/Matamoros\n* `America/Mazatlan` - America/Mazatlan\n* `America/Mendoza` - America/Mendoza\n* `America/Menominee` - America/Menominee\n* `America/Merida` - America/Merida\n* `America/Metlakatla` - America/Metlakatla\n* `America/Mexico_City` - America/Mexico_City\n* `America/Miquelon` - America/Miquelon\n* `America/Moncton` - America/Moncton\n* `America/Monterrey` - America/Monterrey\n* `America/Montevideo` - America/Montevideo\n* `America/Montreal` - America/Montreal\n* `America/Montserrat` - America/Montserrat\n* `America/Nassau` - America/Nassau\n* `America/New_York` - America/New_York\n* `America/Nipigon` - America/Nipigon\n* `America/Nome` - America/Nome\n* `America/Noronha` - America/Noronha\n* `America/North_Dakota/Beulah` - America/North_Dakota/Beulah\n* `America/North_Dakota/Center` - America/North_Dakota/Center\n* `America/North_Dakota/New_Salem` - America/North_Dakota/New_Salem\n* `America/Nuuk` - America/Nuuk\n* `America/Ojinaga` - America/Ojinaga\n* `America/Panama` - America/Panama\n* `America/Pangnirtung` - America/Pangnirtung\n* `America/Paramaribo` - America/Paramaribo\n* `America/Phoenix` - America/Phoenix\n* `America/Port-au-Prince` - America/Port-au-Prince\n* `America/Port_of_Spain` - America/Port_of_Spain\n* `America/Porto_Acre` - America/Porto_Acre\n* `America/Porto_Velho` - America/Porto_Velho\n* `America/Puerto_Rico` - America/Puerto_Rico\n* `America/Punta_Arenas` - America/Punta_Arenas\n* `America/Rainy_River` - America/Rainy_River\n* `America/Rankin_Inlet` - America/Rankin_Inlet\n* `America/Recife` - America/Recife\n* `America/Regina` - America/Regina\n* `America/Resolute` - America/Resolute\n* `America/Rio_Branco` - America/Rio_Branco\n* `America/Rosario` - America/Rosario\n* `America/Santa_Isabel` - America/Santa_Isabel\n* `America/Santarem` - America/Santarem\n* `America/Santiago` - America/Santiago\n* `America/Santo_Domingo` - America/Santo_Domingo\n* `America/Sao_Paulo` - America/Sao_Paulo\n* `America/Scoresbysund` - America/Scoresbysund\n* `America/Shiprock` - America/Shiprock\n* `America/Sitka` - America/Sitka\n* `America/St_Barthelemy` - America/St_Barthelemy\n* `America/St_Johns` - America/St_Johns\n* `America/St_Kitts` - America/St_Kitts\n* `America/St_Lucia` - America/St_Lucia\n* `America/St_Thomas` - America/St_Thomas\n* `America/St_Vincent` - America/St_Vincent\n* `America/Swift_Current` - America/Swift_Current\n* `America/Tegucigalpa` - America/Tegucigalpa\n* `America/Thule` - America/Thule\n* `America/Thunder_Bay` - America/Thunder_Bay\n* `America/Tijuana` - America/Tijuana\n* `America/Toronto` - America/Toronto\n* `America/Tortola` - America/Tortola\n* `America/Vancouver` - America/Vancouver\n* `America/Virgin` - America/Virgin\n* `America/Whitehorse` - America/Whitehorse\n* `America/Winnipeg` - America/Winnipeg\n* `America/Yakutat` - America/Yakutat\n* `America/Yellowknife` - America/Yellowknife\n* `Antarctica/Casey` - Antarctica/Casey\n* `Antarctica/Davis` - Antarctica/Davis\n* `Antarctica/DumontDUrville` - Antarctica/DumontDUrville\n* `Antarctica/Macquarie` - Antarctica/Macquarie\n* `Antarctica/Mawson` - Antarctica/Mawson\n* `Antarctica/McMurdo` - Antarctica/McMurdo\n* `Antarctica/Palmer` - Antarctica/Palmer\n* `Antarctica/Rothera` - Antarctica/Rothera\n* `Antarctica/South_Pole` - Antarctica/South_Pole\n* `Antarctica/Syowa` - Antarctica/Syowa\n* `Antarctica/Troll` - Antarctica/Troll\n* `Antarctica/Vostok` - Antarctica/Vostok\n* `Arctic/Longyearbyen` - Arctic/Longyearbyen\n* `Asia/Aden` - Asia/Aden\n* `Asia/Almaty` - Asia/Almaty\n* `Asia/Amman` - Asia/Amman\n* `Asia/Anadyr` - Asia/Anadyr\n* `Asia/Aqtau` - Asia/Aqtau\n* `Asia/Aqtobe` - Asia/Aqtobe\n* `Asia/Ashgabat` - Asia/Ashgabat\n* `Asia/Ashkhabad` - Asia/Ashkhabad\n* `Asia/Atyrau` - Asia/Atyrau\n* `Asia/Baghdad` - Asia/Baghdad\n* `Asia/Bahrain` - Asia/Bahrain\n* `Asia/Baku` - Asia/Baku\n* `Asia/Bangkok` - Asia/Bangkok\n* `Asia/Barnaul` - Asia/Barnaul\n* `Asia/Beirut` - Asia/Beirut\n* `Asia/Bishkek` - Asia/Bishkek\n* `Asia/Brunei` - Asia/Brunei\n* `Asia/Calcutta` - Asia/Calcutta\n* `Asia/Chita` - Asia/Chita\n* `Asia/Choibalsan` - Asia/Choibalsan\n* `Asia/Chongqing` - Asia/Chongqing\n* `Asia/Chungking` - Asia/Chungking\n* `Asia/Colombo` - Asia/Colombo\n* `Asia/Dacca` - Asia/Dacca\n* `Asia/Damascus` - Asia/Damascus\n* `Asia/Dhaka` - Asia/Dhaka\n* `Asia/Dili` - Asia/Dili\n* `Asia/Dubai` - Asia/Dubai\n* `Asia/Dushanbe` - Asia/Dushanbe\n* `Asia/Famagusta` - Asia/Famagusta\n* `Asia/Gaza` - Asia/Gaza\n* `Asia/Harbin` - Asia/Harbin\n* `Asia/Hebron` - Asia/Hebron\n* `Asia/Ho_Chi_Minh` - Asia/Ho_Chi_Minh\n* `Asia/Hong_Kong` - Asia/Hong_Kong\n* `Asia/Hovd` - Asia/Hovd\n* `Asia/Irkutsk` - Asia/Irkutsk\n* `Asia/Istanbul` - Asia/Istanbul\n* `Asia/Jakarta` - Asia/Jakarta\n* `Asia/Jayapura` - Asia/Jayapura\n* `Asia/Jerusalem` - Asia/Jerusalem\n* `Asia/Kabul` - Asia/Kabul\n* `Asia/Kamchatka` - Asia/Kamchatka\n* `Asia/Karachi` - Asia/Karachi\n* `Asia/Kashgar` - Asia/Kashgar\n* `Asia/Kathmandu` - Asia/Kathmandu\n* `Asia/Katmandu` - Asia/Katmandu\n* `Asia/Khandyga` - Asia/Khandyga\n* `Asia/Kolkata` - Asia/Kolkata\n* `Asia/Krasnoyarsk` - Asia/Krasnoyarsk\n* `Asia/Kuala_Lumpur` - Asia/Kuala_Lumpur\n* `Asia/Kuching` - Asia/Kuching\n* `Asia/Kuwait` - Asia/Kuwait\n* `Asia/Macao` - Asia/Macao\n* `Asia/Macau` - Asia/Macau\n* `Asia/Magadan` - Asia/Magadan\n* `Asia/Makassar` - Asia/Makassar\n* `Asia/Manila` - Asia/Manila\n* `Asia/Muscat` - Asia/Muscat\n* `Asia/Nicosia` - Asia/Nicosia\n* `Asia/Novokuznetsk` - Asia/Novokuznetsk\n* `Asia/Novosibirsk` - Asia/Novosibirsk\n* `Asia/Omsk` - Asia/Omsk\n* `Asia/Oral` - Asia/Oral\n* `Asia/Phnom_Penh` - Asia/Phnom_Penh\n* `Asia/Pontianak` - Asia/Pontianak\n* `Asia/Pyongyang` - Asia/Pyongyang\n* `Asia/Qatar` - Asia/Qatar\n* `Asia/Qostanay` - Asia/Qostanay\n* `Asia/Qyzylorda` - Asia/Qyzylorda\n* `Asia/Rangoon` - Asia/Rangoon\n* `Asia/Riyadh` - Asia/Riyadh\n* `Asia/Saigon` - Asia/Saigon\n* `Asia/Sakhalin` - Asia/Sakhalin\n* `Asia/Samarkand` - Asia/Samarkand\n* `Asia/Seoul` - Asia/Seoul\n* `Asia/Shanghai` - Asia/Shanghai\n* `Asia/Singapore` - Asia/Singapore\n* `Asia/Srednekolymsk` - Asia/Srednekolymsk\n* `Asia/Taipei` - Asia/Taipei\n* `Asia/Tashkent` - Asia/Tashkent\n* `Asia/Tbilisi` - Asia/Tbilisi\n* `Asia/Tehran` - Asia/Tehran\n* `Asia/Tel_Aviv` - Asia/Tel_Aviv\n* `Asia/Thimbu` - Asia/Thimbu\n* `Asia/Thimphu` - Asia/Thimphu\n* `Asia/Tokyo` - Asia/Tokyo\n* `Asia/Tomsk` - Asia/Tomsk\n* `Asia/Ujung_Pandang` - Asia/Ujung_Pandang\n* `Asia/Ulaanbaatar` - Asia/Ulaanbaatar\n* `Asia/Ulan_Bator` - Asia/Ulan_Bator\n* `Asia/Urumqi` - Asia/Urumqi\n* `Asia/Ust-Nera` - Asia/Ust-Nera\n* `Asia/Vientiane` - Asia/Vientiane\n* `Asia/Vladivostok` - Asia/Vladivostok\n* `Asia/Yakutsk` - Asia/Yakutsk\n* `Asia/Yangon` - Asia/Yangon\n* `Asia/Yekaterinburg` - Asia/Yekaterinburg\n* `Asia/Yerevan` - Asia/Yerevan\n* `Atlantic/Azores` - Atlantic/Azores\n* `Atlantic/Bermuda` - Atlantic/Bermuda\n* `Atlantic/Canary` - Atlantic/Canary\n* `Atlantic/Cape_Verde` - Atlantic/Cape_Verde\n* `Atlantic/Faeroe` - Atlantic/Faeroe\n* `Atlantic/Faroe` - Atlantic/Faroe\n* `Atlantic/Jan_Mayen` - Atlantic/Jan_Mayen\n* `Atlantic/Madeira` - Atlantic/Madeira\n* `Atlantic/Reykjavik` - Atlantic/Reykjavik\n* `Atlantic/South_Georgia` - Atlantic/South_Georgia\n* `Atlantic/St_Helena` - Atlantic/St_Helena\n* `Atlantic/Stanley` - Atlantic/Stanley\n* `Australia/ACT` - Australia/ACT\n* `Australia/Adelaide` - Australia/Adelaide\n* `Australia/Brisbane` - Australia/Brisbane\n* `Australia/Broken_Hill` - Australia/Broken_Hill\n* `Australia/Canberra` - Australia/Canberra\n* `Australia/Currie` - Australia/Currie\n* `Australia/Darwin` - Australia/Darwin\n* `Australia/Eucla` - Australia/Eucla\n* `Australia/Hobart` - Australia/Hobart\n* `Australia/LHI` - Australia/LHI\n* `Australia/Lindeman` - Australia/Lindeman\n* `Australia/Lord_Howe` - Australia/Lord_Howe\n* `Australia/Melbourne` - Australia/Melbourne\n* `Australia/NSW` - Australia/NSW\n* `Australia/North` - Australia/North\n* `Australia/Perth` - Australia/Perth\n* `Australia/Queensland` - Australia/Queensland\n* `Australia/South` - Australia/South\n* `Australia/Sydney` - Australia/Sydney\n* `Australia/Tasmania` - Australia/Tasmania\n* `Australia/Victoria` - Australia/Victoria\n* `Australia/West` - Australia/West\n* `Australia/Yancowinna` - Australia/Yancowinna\n* `Brazil/Acre` - Brazil/Acre\n* `Brazil/DeNoronha` - Brazil/DeNoronha\n* `Brazil/East` - Brazil/East\n* `Brazil/West` - Brazil/West\n* `CET` - CET\n* `CST6CDT` - CST6CDT\n* `Canada/Atlantic` - Canada/Atlantic\n* `Canada/Central` - Canada/Central\n* `Canada/Eastern` - Canada/Eastern\n* `Canada/Mountain` - Canada/Mountain\n* `Canada/Newfoundland` - Canada/Newfoundland\n* `Canada/Pacific` - Canada/Pacific\n* `Canada/Saskatchewan` - Canada/Saskatchewan\n* `Canada/Yukon` - Canada/Yukon\n* `Chile/Continental` - Chile/Continental\n* `Chile/EasterIsland` - Chile/EasterIsland\n* `Cuba` - Cuba\n* `EET` - EET\n* `EST` - EST\n* `EST5EDT` - EST5EDT\n* `Egypt` - Egypt\n* `Eire` - Eire\n* `Etc/GMT` - Etc/GMT\n* `Etc/GMT+0` - Etc/GMT+0\n* `Etc/GMT+1` - Etc/GMT+1\n* `Etc/GMT+10` - Etc/GMT+10\n* `Etc/GMT+11` - Etc/GMT+11\n* `Etc/GMT+12` - Etc/GMT+12\n* `Etc/GMT+2` - Etc/GMT+2\n* `Etc/GMT+3` - Etc/GMT+3\n* `Etc/GMT+4` - Etc/GMT+4\n* `Etc/GMT+5` - Etc/GMT+5\n* `Etc/GMT+6` - Etc/GMT+6\n* `Etc/GMT+7` - Etc/GMT+7\n* `Etc/GMT+8` - Etc/GMT+8\n* `Etc/GMT+9` - Etc/GMT+9\n* `Etc/GMT-0` - Etc/GMT-0\n* `Etc/GMT-1` - Etc/GMT-1\n* `Etc/GMT-10` - Etc/GMT-10\n* `Etc/GMT-11` - Etc/GMT-11\n* `Etc/GMT-12` - Etc/GMT-12\n* `Etc/GMT-13` - Etc/GMT-13\n* `Etc/GMT-14` - Etc/GMT-14\n* `Etc/GMT-2` - Etc/GMT-2\n* `Etc/GMT-3` - Etc/GMT-3\n* `Etc/GMT-4` - Etc/GMT-4\n* `Etc/GMT-5` - Etc/GMT-5\n* `Etc/GMT-6` - Etc/GMT-6\n* `Etc/GMT-7` - Etc/GMT-7\n* `Etc/GMT-8` - Etc/GMT-8\n* `Etc/GMT-9` - Etc/GMT-9\n* `Etc/GMT0` - Etc/GMT0\n* `Etc/Greenwich` - Etc/Greenwich\n* `Etc/UCT` - Etc/UCT\n* `Etc/UTC` - Etc/UTC\n* `Etc/Universal` - Etc/Universal\n* `Etc/Zulu` - Etc/Zulu\n* `Europe/Amsterdam` - Europe/Amsterdam\n* `Europe/Andorra` - Europe/Andorra\n* `Europe/Astrakhan` - Europe/Astrakhan\n* `Europe/Athens` - Europe/Athens\n* `Europe/Belfast` - Europe/Belfast\n* `Europe/Belgrade` - Europe/Belgrade\n* `Europe/Berlin` - Europe/Berlin\n* `Europe/Bratislava` - Europe/Bratislava\n* `Europe/Brussels` - Europe/Brussels\n* `Europe/Bucharest` - Europe/Bucharest\n* `Europe/Budapest` - Europe/Budapest\n* `Europe/Busingen` - Europe/Busingen\n* `Europe/Chisinau` - Europe/Chisinau\n* `Europe/Copenhagen` - Europe/Copenhagen\n* `Europe/Dublin` - Europe/Dublin\n* `Europe/Gibraltar` - Europe/Gibraltar\n* `Europe/Guernsey` - Europe/Guernsey\n* `Europe/Helsinki` - Europe/Helsinki\n* `Europe/Isle_of_Man` - Europe/Isle_of_Man\n* `Europe/Istanbul` - Europe/Istanbul\n* `Europe/Jersey` - Europe/Jersey\n* `Europe/Kaliningrad` - Europe/Kaliningrad\n* `Europe/Kiev` - Europe/Kiev\n* `Europe/Kirov` - Europe/Kirov\n* `Europe/Kyiv` - Europe/Kyiv\n* `Europe/Lisbon` - Europe/Lisbon\n* `Europe/Ljubljana` - Europe/Ljubljana\n* `Europe/London` - Europe/London\n* `Europe/Luxembourg` - Europe/Luxembourg\n* `Europe/Madrid` - Europe/Madrid\n* `Europe/Malta` - Europe/Malta\n* `Europe/Mariehamn` - Europe/Mariehamn\n* `Europe/Minsk` - Europe/Minsk\n* `Europe/Monaco` - Europe/Monaco\n* `Europe/Moscow` - Europe/Moscow\n* `Europe/Nicosia` - Europe/Nicosia\n* `Europe/Oslo` - Europe/Oslo\n* `Europe/Paris` - Europe/Paris\n* `Europe/Podgorica` - Europe/Podgorica\n* `Europe/Prague` - Europe/Prague\n* `Europe/Riga` - Europe/Riga\n* `Europe/Rome` - Europe/Rome\n* `Europe/Samara` - Europe/Samara\n* `Europe/San_Marino` - Europe/San_Marino\n* `Europe/Sarajevo` - Europe/Sarajevo\n* `Europe/Saratov` - Europe/Saratov\n* `Europe/Simferopol` - Europe/Simferopol\n* `Europe/Skopje` - Europe/Skopje\n* `Europe/Sofia` - Europe/Sofia\n* `Europe/Stockholm` - Europe/Stockholm\n* `Europe/Tallinn` - Europe/Tallinn\n* `Europe/Tirane` - Europe/Tirane\n* `Europe/Tiraspol` - Europe/Tiraspol\n* `Europe/Ulyanovsk` - Europe/Ulyanovsk\n* `Europe/Uzhgorod` - Europe/Uzhgorod\n* `Europe/Vaduz` - Europe/Vaduz\n* `Europe/Vatican` - Europe/Vatican\n* `Europe/Vienna` - Europe/Vienna\n* `Europe/Vilnius` - Europe/Vilnius\n* `Europe/Volgograd` - Europe/Volgograd\n* `Europe/Warsaw` - Europe/Warsaw\n* `Europe/Zagreb` - Europe/Zagreb\n* `Europe/Zaporozhye` - Europe/Zaporozhye\n* `Europe/Zurich` - Europe/Zurich\n* `GB` - GB\n* `GB-Eire` - GB-Eire\n* `GMT` - GMT\n* `GMT+0` - GMT+0\n* `GMT-0` - GMT-0\n* `GMT0` - GMT0\n* `Greenwich` - Greenwich\n* `HST` - HST\n* `Hongkong` - Hongkong\n* `Iceland` - Iceland\n* `Indian/Antananarivo` - Indian/Antananarivo\n* `Indian/Chagos` - Indian/Chagos\n* `Indian/Christmas` - Indian/Christmas\n* `Indian/Cocos` - Indian/Cocos\n* `Indian/Comoro` - Indian/Comoro\n* `Indian/Kerguelen` - Indian/Kerguelen\n* `Indian/Mahe` - Indian/Mahe\n* `Indian/Maldives` - Indian/Maldives\n* `Indian/Mauritius` - Indian/Mauritius\n* `Indian/Mayotte` - Indian/Mayotte\n* `Indian/Reunion` - Indian/Reunion\n* `Iran` - Iran\n* `Israel` - Israel\n* `Jamaica` - Jamaica\n* `Japan` - Japan\n* `Kwajalein` - Kwajalein\n* `Libya` - Libya\n* `MET` - MET\n* `MST` - MST\n* `MST7MDT` - MST7MDT\n* `Mexico/BajaNorte` - Mexico/BajaNorte\n* `Mexico/BajaSur` - Mexico/BajaSur\n* `Mexico/General` - Mexico/General\n* `NZ` - NZ\n* `NZ-CHAT` - NZ-CHAT\n* `Navajo` - Navajo\n* `PRC` - PRC\n* `PST8PDT` - PST8PDT\n* `Pacific/Apia` - Pacific/Apia\n* `Pacific/Auckland` - Pacific/Auckland\n* `Pacific/Bougainville` - Pacific/Bougainville\n* `Pacific/Chatham` - Pacific/Chatham\n* `Pacific/Chuuk` - Pacific/Chuuk\n* `Pacific/Easter` - Pacific/Easter\n* `Pacific/Efate` - Pacific/Efate\n* `Pacific/Enderbury` - Pacific/Enderbury\n* `Pacific/Fakaofo` - Pacific/Fakaofo\n* `Pacific/Fiji` - Pacific/Fiji\n* `Pacific/Funafuti` - Pacific/Funafuti\n* `Pacific/Galapagos` - Pacific/Galapagos\n* `Pacific/Gambier` - Pacific/Gambier\n* `Pacific/Guadalcanal` - Pacific/Guadalcanal\n* `Pacific/Guam` - Pacific/Guam\n* `Pacific/Honolulu` - Pacific/Honolulu\n* `Pacific/Johnston` - Pacific/Johnston\n* `Pacific/Kanton` - Pacific/Kanton\n* `Pacific/Kiritimati` - Pacific/Kiritimati\n* `Pacific/Kosrae` - Pacific/Kosrae\n* `Pacific/Kwajalein` - Pacific/Kwajalein\n* `Pacific/Majuro` - Pacific/Majuro\n* `Pacific/Marquesas` - Pacific/Marquesas\n* `Pacific/Midway` - Pacific/Midway\n* `Pacific/Nauru` - Pacific/Nauru\n* `Pacific/Niue` - Pacific/Niue\n* `Pacific/Norfolk` - Pacific/Norfolk\n* `Pacific/Noumea` - Pacific/Noumea\n* `Pacific/Pago_Pago` - Pacific/Pago_Pago\n* `Pacific/Palau` - Pacific/Palau\n* `Pacific/Pitcairn` - Pacific/Pitcairn\n* `Pacific/Pohnpei` - Pacific/Pohnpei\n* `Pacific/Ponape` - Pacific/Ponape\n* `Pacific/Port_Moresby` - Pacific/Port_Moresby\n* `Pacific/Rarotonga` - Pacific/Rarotonga\n* `Pacific/Saipan` - Pacific/Saipan\n* `Pacific/Samoa` - Pacific/Samoa\n* `Pacific/Tahiti` - Pacific/Tahiti\n* `Pacific/Tarawa` - Pacific/Tarawa\n* `Pacific/Tongatapu` - Pacific/Tongatapu\n* `Pacific/Truk` - Pacific/Truk\n* `Pacific/Wake` - Pacific/Wake\n* `Pacific/Wallis` - Pacific/Wallis\n* `Pacific/Yap` - Pacific/Yap\n* `Poland` - Poland\n* `Portugal` - Portugal\n* `ROC` - ROC\n* `ROK` - ROK\n* `Singapore` - Singapore\n* `Turkey` - Turkey\n* `UCT` - UCT\n* `US/Alaska` - US/Alaska\n* `US/Aleutian` - US/Aleutian\n* `US/Arizona` - US/Arizona\n* `US/Central` - US/Central\n* `US/East-Indiana` - US/East-Indiana\n* `US/Eastern` - US/Eastern\n* `US/Hawaii` - US/Hawaii\n* `US/Indiana-Starke` - US/Indiana-Starke\n* `US/Michigan` - US/Michigan\n* `US/Mountain` - US/Mountain\n* `US/Pacific` - US/Pacific\n* `US/Samoa` - US/Samoa\n* `UTC` - UTC\n* `Universal` - Universal\n* `W-SU` - W-SU\n* `WET` - WET\n* `Zulu` - Zulu'
            ),
        data_attributes: zod
            .unknown()
            .optional()
            .describe(
                "Element attributes that posthog-js should capture as action identifiers (e.g. `['data-attr']`)."
            ),
        person_display_name_properties: zod
            .array(zod.string().max(organizationsProjectsPartialUpdateBodyPersonDisplayNamePropertiesItemMax))
            .nullish()
            .describe('Ordered list of person properties used to render a human-friendly display name in the UI.'),
        correlation_config: zod.unknown().optional(),
        autocapture_opt_out: zod
            .boolean()
            .nullish()
            .describe('Disables posthog-js autocapture (clicks, page views) when true.'),
        autocapture_exceptions_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of JavaScript exceptions via the SDK.'),
        autocapture_web_vitals_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of Core Web Vitals performance metrics.'),
        autocapture_web_vitals_allowed_metrics: zod.unknown().optional(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().optional(),
        capture_console_log_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing browser console logs alongside session replays.'),
        capture_performance_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing performance timing and network requests.'),
        session_recording_opt_in: zod
            .boolean()
            .optional()
            .describe('Enables session replay recording for this project.'),
        session_recording_sample_rate: zod
            .stringFormat('decimal', organizationsProjectsPartialUpdateBodySessionRecordingSampleRateRegExp)
            .nullish()
            .describe(
                'Fraction of sessions to record, as a decimal string between `0.00` and `1.00` (e.g. `0.1` = 10%).'
            ),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(organizationsProjectsPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMin)
            .max(organizationsProjectsPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMax)
            .nullish()
            .describe('Skip saving sessions shorter than this many milliseconds.'),
        session_recording_linked_flag: zod.unknown().optional(),
        session_recording_network_payload_capture_config: zod.unknown().optional(),
        session_recording_masking_config: zod.unknown().optional(),
        session_recording_url_trigger_config: zod.array(zod.unknown()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(organizationsProjectsPartialUpdateBodySessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .optional()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .describe('* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years')
            .optional()
            .describe(
                'How long to retain new session recordings. One of `30d`, `90d`, `1y`, or `5y` (availability depends on plan).\n\n* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years'
            ),
        session_replay_config: zod.unknown().optional(),
        survey_config: zod.unknown().optional(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([zod.union([zod.literal(0), zod.literal(1)]).describe('* `0` - Sunday\n* `1` - Monday'), zod.null()])
            .optional()
            .describe(
                'First day of the week for date range filters. 0 = Sunday, 1 = Monday.\n\n* `0` - Sunday\n* `1` - Monday'
            ),
        primary_dashboard: zod
            .number()
            .nullish()
            .describe("ID of the dashboard shown as the project's default landing dashboard."),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod
            .array(zod.string().max(organizationsProjectsPartialUpdateBodyRecordingDomainsItemMax).nullable())
            .nullish()
            .describe('Origins permitted to record session replays and heatmaps. Empty list allows all origins.'),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().optional(),
        modifiers: zod.unknown().optional(),
        has_completed_onboarding_for: zod.unknown().optional(),
        surveys_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables displaying surveys via posthog-js on allowed origins.'),
        heatmaps_opt_in: zod.boolean().nullish().describe('Enables heatmap recording on pages that host posthog-js.'),
        flags_persistence_default: zod
            .boolean()
            .nullish()
            .describe('Default value for the `persist` option on newly created feature flags.'),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'),
                zod.enum(['']),
                zod.null(),
            ])
            .optional()
            .describe(
                'Whether this project serves B2B or B2C customers. Used to optimize default UI layouts.\n\n* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'
            ),
        conversations_enabled: zod
            .boolean()
            .nullish()
            .describe('Enables the customer conversations / live chat product for this project.'),
        conversations_settings: zod.unknown().optional(),
        logs_settings: zod.unknown().optional(),
        proactive_tasks_enabled: zod.boolean().nullish(),
        revenue_analytics_config: zod
            .object({
                base_currency: zod
                    .enum([
                        'AED',
                        'AFN',
                        'ALL',
                        'AMD',
                        'ANG',
                        'AOA',
                        'ARS',
                        'AUD',
                        'AWG',
                        'AZN',
                        'BAM',
                        'BBD',
                        'BDT',
                        'BGN',
                        'BHD',
                        'BIF',
                        'BMD',
                        'BND',
                        'BOB',
                        'BRL',
                        'BSD',
                        'BTC',
                        'BTN',
                        'BWP',
                        'BYN',
                        'BZD',
                        'CAD',
                        'CDF',
                        'CHF',
                        'CLP',
                        'CNY',
                        'COP',
                        'CRC',
                        'CVE',
                        'CZK',
                        'DJF',
                        'DKK',
                        'DOP',
                        'DZD',
                        'EGP',
                        'ERN',
                        'ETB',
                        'EUR',
                        'FJD',
                        'GBP',
                        'GEL',
                        'GHS',
                        'GIP',
                        'GMD',
                        'GNF',
                        'GTQ',
                        'GYD',
                        'HKD',
                        'HNL',
                        'HRK',
                        'HTG',
                        'HUF',
                        'IDR',
                        'ILS',
                        'INR',
                        'IQD',
                        'IRR',
                        'ISK',
                        'JMD',
                        'JOD',
                        'JPY',
                        'KES',
                        'KGS',
                        'KHR',
                        'KMF',
                        'KRW',
                        'KWD',
                        'KYD',
                        'KZT',
                        'LAK',
                        'LBP',
                        'LKR',
                        'LRD',
                        'LTL',
                        'LVL',
                        'LSL',
                        'LYD',
                        'MAD',
                        'MDL',
                        'MGA',
                        'MKD',
                        'MMK',
                        'MNT',
                        'MOP',
                        'MRU',
                        'MTL',
                        'MUR',
                        'MVR',
                        'MWK',
                        'MXN',
                        'MYR',
                        'MZN',
                        'NAD',
                        'NGN',
                        'NIO',
                        'NOK',
                        'NPR',
                        'NZD',
                        'OMR',
                        'PAB',
                        'PEN',
                        'PGK',
                        'PHP',
                        'PKR',
                        'PLN',
                        'PYG',
                        'QAR',
                        'RON',
                        'RSD',
                        'RUB',
                        'RWF',
                        'SAR',
                        'SBD',
                        'SCR',
                        'SDG',
                        'SEK',
                        'SGD',
                        'SRD',
                        'SSP',
                        'STN',
                        'SYP',
                        'SZL',
                        'THB',
                        'TJS',
                        'TMT',
                        'TND',
                        'TOP',
                        'TRY',
                        'TTD',
                        'TWD',
                        'TZS',
                        'UAH',
                        'UGX',
                        'USD',
                        'UYU',
                        'UZS',
                        'VES',
                        'VND',
                        'VUV',
                        'WST',
                        'XAF',
                        'XCD',
                        'XOF',
                        'XPF',
                        'YER',
                        'ZAR',
                        'ZMW',
                    ])
                    .optional()
                    .describe(
                        '* `AED` - AED\n* `AFN` - AFN\n* `ALL` - ALL\n* `AMD` - AMD\n* `ANG` - ANG\n* `AOA` - AOA\n* `ARS` - ARS\n* `AUD` - AUD\n* `AWG` - AWG\n* `AZN` - AZN\n* `BAM` - BAM\n* `BBD` - BBD\n* `BDT` - BDT\n* `BGN` - BGN\n* `BHD` - BHD\n* `BIF` - BIF\n* `BMD` - BMD\n* `BND` - BND\n* `BOB` - BOB\n* `BRL` - BRL\n* `BSD` - BSD\n* `BTC` - BTC\n* `BTN` - BTN\n* `BWP` - BWP\n* `BYN` - BYN\n* `BZD` - BZD\n* `CAD` - CAD\n* `CDF` - CDF\n* `CHF` - CHF\n* `CLP` - CLP\n* `CNY` - CNY\n* `COP` - COP\n* `CRC` - CRC\n* `CVE` - CVE\n* `CZK` - CZK\n* `DJF` - DJF\n* `DKK` - DKK\n* `DOP` - DOP\n* `DZD` - DZD\n* `EGP` - EGP\n* `ERN` - ERN\n* `ETB` - ETB\n* `EUR` - EUR\n* `FJD` - FJD\n* `GBP` - GBP\n* `GEL` - GEL\n* `GHS` - GHS\n* `GIP` - GIP\n* `GMD` - GMD\n* `GNF` - GNF\n* `GTQ` - GTQ\n* `GYD` - GYD\n* `HKD` - HKD\n* `HNL` - HNL\n* `HRK` - HRK\n* `HTG` - HTG\n* `HUF` - HUF\n* `IDR` - IDR\n* `ILS` - ILS\n* `INR` - INR\n* `IQD` - IQD\n* `IRR` - IRR\n* `ISK` - ISK\n* `JMD` - JMD\n* `JOD` - JOD\n* `JPY` - JPY\n* `KES` - KES\n* `KGS` - KGS\n* `KHR` - KHR\n* `KMF` - KMF\n* `KRW` - KRW\n* `KWD` - KWD\n* `KYD` - KYD\n* `KZT` - KZT\n* `LAK` - LAK\n* `LBP` - LBP\n* `LKR` - LKR\n* `LRD` - LRD\n* `LTL` - LTL\n* `LVL` - LVL\n* `LSL` - LSL\n* `LYD` - LYD\n* `MAD` - MAD\n* `MDL` - MDL\n* `MGA` - MGA\n* `MKD` - MKD\n* `MMK` - MMK\n* `MNT` - MNT\n* `MOP` - MOP\n* `MRU` - MRU\n* `MTL` - MTL\n* `MUR` - MUR\n* `MVR` - MVR\n* `MWK` - MWK\n* `MXN` - MXN\n* `MYR` - MYR\n* `MZN` - MZN\n* `NAD` - NAD\n* `NGN` - NGN\n* `NIO` - NIO\n* `NOK` - NOK\n* `NPR` - NPR\n* `NZD` - NZD\n* `OMR` - OMR\n* `PAB` - PAB\n* `PEN` - PEN\n* `PGK` - PGK\n* `PHP` - PHP\n* `PKR` - PKR\n* `PLN` - PLN\n* `PYG` - PYG\n* `QAR` - QAR\n* `RON` - RON\n* `RSD` - RSD\n* `RUB` - RUB\n* `RWF` - RWF\n* `SAR` - SAR\n* `SBD` - SBD\n* `SCR` - SCR\n* `SDG` - SDG\n* `SEK` - SEK\n* `SGD` - SGD\n* `SRD` - SRD\n* `SSP` - SSP\n* `STN` - STN\n* `SYP` - SYP\n* `SZL` - SZL\n* `THB` - THB\n* `TJS` - TJS\n* `TMT` - TMT\n* `TND` - TND\n* `TOP` - TOP\n* `TRY` - TRY\n* `TTD` - TTD\n* `TWD` - TWD\n* `TZS` - TZS\n* `UAH` - UAH\n* `UGX` - UGX\n* `USD` - USD\n* `UYU` - UYU\n* `UZS` - UZS\n* `VES` - VES\n* `VND` - VND\n* `VUV` - VUV\n* `WST` - WST\n* `XAF` - XAF\n* `XCD` - XCD\n* `XOF` - XOF\n* `XPF` - XPF\n* `YER` - YER\n* `ZAR` - ZAR\n* `ZMW` - ZMW'
                    ),
                events: zod.unknown().optional(),
                goals: zod.unknown().optional(),
                filter_test_accounts: zod.boolean().optional(),
            })
            .optional(),
        marketing_analytics_config: zod
            .object({
                sources_map: zod.unknown().optional(),
                conversion_goals: zod.unknown().optional(),
                attribution_window_days: zod
                    .number()
                    .min(1)
                    .max(organizationsProjectsPartialUpdateBodyMarketingAnalyticsConfigAttributionWindowDaysMax)
                    .optional(),
                attribution_mode: zod
                    .enum(['first_touch', 'last_touch', 'linear', 'time_decay', 'position_based'])
                    .optional()
                    .describe(
                        '* `first_touch` - First Touch\n* `last_touch` - Last Touch\n* `linear` - Linear\n* `time_decay` - Time Decay\n* `position_based` - Position Based'
                    ),
                campaign_name_mappings: zod.unknown().optional(),
                custom_source_mappings: zod.unknown().optional(),
                campaign_field_preferences: zod.unknown().optional(),
            })
            .optional(),
        customer_analytics_config: zod
            .object({
                activity_event: zod.unknown().optional().describe('Event used as the activity signal (DAU/WAU/MAU).'),
                signup_pageview_event: zod
                    .unknown()
                    .optional()
                    .describe('Event used to count signup pageviews on dashboards.'),
                signup_event: zod.unknown().optional().describe('Event used to count signups on dashboards.'),
                subscription_event: zod
                    .unknown()
                    .optional()
                    .describe('Event used to count subscriptions on dashboards.'),
                payment_event: zod.unknown().optional().describe('Event used to count payments on dashboards.'),
                account_group_type_index: zod
                    .number()
                    .nullish()
                    .describe(
                        'Index of the group type to treat as an Account in customer analytics. Must reference an existing group type configured for the project.'
                    ),
            })
            .optional(),
        workflows_config: zod
            .object({
                capture_workflows_engagement_events: zod
                    .boolean()
                    .optional()
                    .describe(
                        'When enabled, workflows engagement activity (email sends, opens, clicks, bounces, spam reports, unsubscribes) is captured as standard PostHog events ($workflows_email_*) alongside the existing workflow metrics.'
                    ),
            })
            .optional(),
        base_currency: zod
            .enum([
                'AED',
                'AFN',
                'ALL',
                'AMD',
                'ANG',
                'AOA',
                'ARS',
                'AUD',
                'AWG',
                'AZN',
                'BAM',
                'BBD',
                'BDT',
                'BGN',
                'BHD',
                'BIF',
                'BMD',
                'BND',
                'BOB',
                'BRL',
                'BSD',
                'BTC',
                'BTN',
                'BWP',
                'BYN',
                'BZD',
                'CAD',
                'CDF',
                'CHF',
                'CLP',
                'CNY',
                'COP',
                'CRC',
                'CVE',
                'CZK',
                'DJF',
                'DKK',
                'DOP',
                'DZD',
                'EGP',
                'ERN',
                'ETB',
                'EUR',
                'FJD',
                'GBP',
                'GEL',
                'GHS',
                'GIP',
                'GMD',
                'GNF',
                'GTQ',
                'GYD',
                'HKD',
                'HNL',
                'HRK',
                'HTG',
                'HUF',
                'IDR',
                'ILS',
                'INR',
                'IQD',
                'IRR',
                'ISK',
                'JMD',
                'JOD',
                'JPY',
                'KES',
                'KGS',
                'KHR',
                'KMF',
                'KRW',
                'KWD',
                'KYD',
                'KZT',
                'LAK',
                'LBP',
                'LKR',
                'LRD',
                'LTL',
                'LVL',
                'LSL',
                'LYD',
                'MAD',
                'MDL',
                'MGA',
                'MKD',
                'MMK',
                'MNT',
                'MOP',
                'MRU',
                'MTL',
                'MUR',
                'MVR',
                'MWK',
                'MXN',
                'MYR',
                'MZN',
                'NAD',
                'NGN',
                'NIO',
                'NOK',
                'NPR',
                'NZD',
                'OMR',
                'PAB',
                'PEN',
                'PGK',
                'PHP',
                'PKR',
                'PLN',
                'PYG',
                'QAR',
                'RON',
                'RSD',
                'RUB',
                'RWF',
                'SAR',
                'SBD',
                'SCR',
                'SDG',
                'SEK',
                'SGD',
                'SRD',
                'SSP',
                'STN',
                'SYP',
                'SZL',
                'THB',
                'TJS',
                'TMT',
                'TND',
                'TOP',
                'TRY',
                'TTD',
                'TWD',
                'TZS',
                'UAH',
                'UGX',
                'USD',
                'UYU',
                'UZS',
                'VES',
                'VND',
                'VUV',
                'WST',
                'XAF',
                'XCD',
                'XOF',
                'XPF',
                'YER',
                'ZAR',
                'ZMW',
            ])
            .optional()
            .describe(
                '* `AED` - AED\n* `AFN` - AFN\n* `ALL` - ALL\n* `AMD` - AMD\n* `ANG` - ANG\n* `AOA` - AOA\n* `ARS` - ARS\n* `AUD` - AUD\n* `AWG` - AWG\n* `AZN` - AZN\n* `BAM` - BAM\n* `BBD` - BBD\n* `BDT` - BDT\n* `BGN` - BGN\n* `BHD` - BHD\n* `BIF` - BIF\n* `BMD` - BMD\n* `BND` - BND\n* `BOB` - BOB\n* `BRL` - BRL\n* `BSD` - BSD\n* `BTC` - BTC\n* `BTN` - BTN\n* `BWP` - BWP\n* `BYN` - BYN\n* `BZD` - BZD\n* `CAD` - CAD\n* `CDF` - CDF\n* `CHF` - CHF\n* `CLP` - CLP\n* `CNY` - CNY\n* `COP` - COP\n* `CRC` - CRC\n* `CVE` - CVE\n* `CZK` - CZK\n* `DJF` - DJF\n* `DKK` - DKK\n* `DOP` - DOP\n* `DZD` - DZD\n* `EGP` - EGP\n* `ERN` - ERN\n* `ETB` - ETB\n* `EUR` - EUR\n* `FJD` - FJD\n* `GBP` - GBP\n* `GEL` - GEL\n* `GHS` - GHS\n* `GIP` - GIP\n* `GMD` - GMD\n* `GNF` - GNF\n* `GTQ` - GTQ\n* `GYD` - GYD\n* `HKD` - HKD\n* `HNL` - HNL\n* `HRK` - HRK\n* `HTG` - HTG\n* `HUF` - HUF\n* `IDR` - IDR\n* `ILS` - ILS\n* `INR` - INR\n* `IQD` - IQD\n* `IRR` - IRR\n* `ISK` - ISK\n* `JMD` - JMD\n* `JOD` - JOD\n* `JPY` - JPY\n* `KES` - KES\n* `KGS` - KGS\n* `KHR` - KHR\n* `KMF` - KMF\n* `KRW` - KRW\n* `KWD` - KWD\n* `KYD` - KYD\n* `KZT` - KZT\n* `LAK` - LAK\n* `LBP` - LBP\n* `LKR` - LKR\n* `LRD` - LRD\n* `LTL` - LTL\n* `LVL` - LVL\n* `LSL` - LSL\n* `LYD` - LYD\n* `MAD` - MAD\n* `MDL` - MDL\n* `MGA` - MGA\n* `MKD` - MKD\n* `MMK` - MMK\n* `MNT` - MNT\n* `MOP` - MOP\n* `MRU` - MRU\n* `MTL` - MTL\n* `MUR` - MUR\n* `MVR` - MVR\n* `MWK` - MWK\n* `MXN` - MXN\n* `MYR` - MYR\n* `MZN` - MZN\n* `NAD` - NAD\n* `NGN` - NGN\n* `NIO` - NIO\n* `NOK` - NOK\n* `NPR` - NPR\n* `NZD` - NZD\n* `OMR` - OMR\n* `PAB` - PAB\n* `PEN` - PEN\n* `PGK` - PGK\n* `PHP` - PHP\n* `PKR` - PKR\n* `PLN` - PLN\n* `PYG` - PYG\n* `QAR` - QAR\n* `RON` - RON\n* `RSD` - RSD\n* `RUB` - RUB\n* `RWF` - RWF\n* `SAR` - SAR\n* `SBD` - SBD\n* `SCR` - SCR\n* `SDG` - SDG\n* `SEK` - SEK\n* `SGD` - SGD\n* `SRD` - SRD\n* `SSP` - SSP\n* `STN` - STN\n* `SYP` - SYP\n* `SZL` - SZL\n* `THB` - THB\n* `TJS` - TJS\n* `TMT` - TMT\n* `TND` - TND\n* `TOP` - TOP\n* `TRY` - TRY\n* `TTD` - TTD\n* `TWD` - TWD\n* `TZS` - TZS\n* `UAH` - UAH\n* `UGX` - UGX\n* `USD` - USD\n* `UYU` - UYU\n* `UZS` - UZS\n* `VES` - VES\n* `VND` - VND\n* `VUV` - VUV\n* `WST` - WST\n* `XAF` - XAF\n* `XCD` - XCD\n* `XOF` - XOF\n* `XPF` - XPF\n* `YER` - YER\n* `ZAR` - ZAR\n* `ZMW` - ZMW'
            ),
        capture_dead_clicks: zod
            .boolean()
            .nullish()
            .describe('Enables capturing clicks that had no effect (rage-click detection).'),
        cookieless_server_hash_mode: zod
            .union([
                zod
                    .union([zod.literal(0), zod.literal(1), zod.literal(2)])
                    .describe('* `0` - Disabled\n* `1` - Stateless\n* `2` - Stateful'),
                zod.null(),
            ])
            .optional(),
        human_friendly_comparison_periods: zod.boolean().nullish(),
        feature_flag_confirmation_enabled: zod.boolean().nullish(),
        feature_flag_confirmation_message: zod.string().nullish(),
        default_evaluation_contexts_enabled: zod
            .boolean()
            .nullish()
            .describe('Whether to automatically apply default evaluation contexts to new feature flags'),
        require_evaluation_contexts: zod
            .boolean()
            .nullish()
            .describe('Whether to require at least one evaluation context tag when creating new feature flags'),
        default_data_theme: zod
            .number()
            .min(organizationsProjectsPartialUpdateBodyDefaultDataThemeMin)
            .max(organizationsProjectsPartialUpdateBodyDefaultDataThemeMax)
            .nullish(),
        onboarding_tasks: zod.unknown().optional(),
        web_analytics_pre_aggregated_tables_enabled: zod.boolean().nullish(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * The file tree for the desktop product surface. Reuses all FileSystemViewSet behaviour but is
 * scoped to the "desktop" surface, so its tree is fully isolated from the default "web" tree.
 *
 * Adds per-folder, versioned markdown instructions describing the contents of a folder.
 */
export const DesktopFileSystemListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DesktopFileSystemListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    search: zod.string().optional().describe('A search term.'),
})

/**
 * The file tree for the desktop product surface. Reuses all FileSystemViewSet behaviour but is
 * scoped to the "desktop" surface, so its tree is fully isolated from the default "web" tree.
 *
 * Adds per-folder, versioned markdown instructions describing the contents of a folder.
 */
export const DesktopFileSystemCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const desktopFileSystemCreateBodyTypeMax = 100

export const desktopFileSystemCreateBodyRefMax = 100

export const DesktopFileSystemCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(desktopFileSystemCreateBodyTypeMax).optional(),
    ref: zod.string().max(desktopFileSystemCreateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().optional(),
    shortcut: zod.boolean().nullish(),
})

/**
 * The file tree for the desktop product surface. Reuses all FileSystemViewSet behaviour but is
 * scoped to the "desktop" surface, so its tree is fully isolated from the default "web" tree.
 *
 * Adds per-folder, versioned markdown instructions describing the contents of a folder.
 */
export const DesktopFileSystemRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this file system.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Publish a new version of a freeform canvas's React source.
 *
 * Merges into the dashboard row's `meta` (never replaces it), so existing
 * keys like `channelId`/`templateId` survive. Appends a full-file version
 * snapshot and points `currentVersionId` at it — the server-side mirror of
 * the app's dashboardsService.saveFreeform.
 */
export const DesktopFileSystemCanvasPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this file system.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DesktopFileSystemCanvasPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        code: zod.string().optional(),
        prompt: zod.string().optional(),
        name: zod.string().optional(),
    })
    .describe("Payload for publishing a freeform canvas's React source via the agent.")

/**
 * Return the latest non-deleted instructions for this folder.
 */
export const DesktopFileSystemInstructionsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this file system.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Publish a new version of the folder's instructions.
 */
export const DesktopFileSystemInstructionsPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this file system.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const desktopFileSystemInstructionsPartialUpdateBodyBaseVersionMin = 0

export const DesktopFileSystemInstructionsPartialUpdateBody = /* @__PURE__ */ zod.object({
    content: zod.string().optional().describe('Full markdown instructions to publish as a new version for the folder.'),
    base_version: zod
        .number()
        .min(desktopFileSystemInstructionsPartialUpdateBodyBaseVersionMin)
        .optional()
        .describe(
            "Latest version you are editing from, for optimistic concurrency. If provided and the folder's instructions have changed since, the request fails with 409. Use 0 when no instructions exist yet."
        ),
})

/**
 * Retrieve a user's profile and settings. Pass `@me` as the UUID to fetch the authenticated user; non-staff callers may only access their own account.
 */
export const UsersRetrieveParams = /* @__PURE__ */ zod.object({
    uuid: zod.string(),
})

/**
 * Update one or more of the authenticated user's profile fields or settings.
 */
export const UsersPartialUpdateParams = /* @__PURE__ */ zod.object({
    uuid: zod.string(),
})

export const usersPartialUpdateBodyFirstNameMax = 150

export const usersPartialUpdateBodyLastNameMax = 150

export const usersPartialUpdateBodyEmailMax = 254

export const usersPartialUpdateBodyPasswordMax = 128

export const UsersPartialUpdateBody = /* @__PURE__ */ zod.object({
    first_name: zod.string().max(usersPartialUpdateBodyFirstNameMax).optional(),
    last_name: zod.string().max(usersPartialUpdateBodyLastNameMax).optional(),
    email: zod.email().max(usersPartialUpdateBodyEmailMax).optional(),
    notification_settings: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Map of notification preferences. Keys include `plugin_disabled`, `all_weekly_report_disabled`, `project_weekly_digest_disabled`, `error_tracking_weekly_digest_project_enabled`, `web_analytics_weekly_digest_project_enabled`, `organization_member_join_email_disabled`, `data_pipeline_error_threshold` (number between 0.0 and 1.0), and other per-topic switches. Values are either booleans, or (for per-project/per-resource keys) a map of IDs to booleans. Only the keys you send are updated — other preferences stay as-is.'
        ),
    anonymize_data: zod
        .boolean()
        .nullish()
        .describe('Whether PostHog should anonymize events captured for this user when identified.'),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('* `disabled` - disabled\n* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersPartialUpdateBodyPasswordMax).optional(),
    current_password: zod
        .string()
        .optional()
        .describe(
            "The user's current password. Required when changing `password` if the user already has a usable password set."
        ),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().optional(),
    theme_mode: zod
        .union([
            zod.enum(['light', 'dark', 'system']).describe('* `light` - Light\n* `dark` - Dark\n* `system` - System'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    hedgehog_config: zod.unknown().optional(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('* `above` - Above\n* `below` - Below\n* `hidden` - Hidden'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
        ),
    hide_mcp_hints: zod
        .boolean()
        .optional()
        .describe(
            'When true, the user has opted out of in-app hints promoting the PostHog MCP integration after taking actions.'
        ),
})
