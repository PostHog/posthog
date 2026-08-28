use std::borrow::Cow;

use simd_json::borrowed::{Object, Value};
use simd_json::prelude::Writable;
use simd_json::StaticNode;

use crate::json::{as_array, as_object, as_str, key};

// Keep this policy aligned with posthog-js/packages/browser/src/extensions/replay/external/json-ld.ts.
const MAX_JSON_LD_LENGTH: usize = 100_000;
const MAX_JSON_LD_OUTPUT_LENGTH: usize = 20_000;
const SCHEMA_CONTEXT: &str = "https://schema.org";
const TYPE_INDEPENDENT_LEAF_PROPERTIES: &str =
    "actionStatus availability bestRating contentRating encodingFormat eventAttendanceMode eventStatus highPrice inLanguage isAccessibleForFree isFamilyFriendly itemCondition itemListOrder lowPrice maximumAttendeeCapacity nonprofitStatus numberOfItems offerCount position price priceCurrency priceValidUntil publicAccess ratingCount ratingValue reviewCount smokingAllowed worstRating";
const ACTION_TYPES: &str =
    "Action BorrowAction ReadAction SearchAction SeekToAction SolveMathAction WatchAction";
const ORGANIZATION_TYPES: &str =
    "AutoDealer Bakery BarOrPub CafeOrCoffeeShop CollegeOrUniversity Corporation DaySpa Dentist EducationalOrganization Electrician FoodEstablishment GovernmentOrganization HealthClub Hotel LegalService Library LibrarySystem LocalBusiness Locksmith LodgingBusiness MedicalBusiness NGO OnlineStore Organization PerformingGroup Pharmacy Physician Plumber RealEstateAgent Restaurant School SportsOrganization Store";
const PLACE_TYPES: &str = "Accommodation AdministrativeArea Country Place State";
const CREATIVE_WORK_TYPES: &str =
    "3DModel AboutPage Answer Article AudioObject Blog BlogPosting Book Clip CollectionPage Comment ContactPage Course CreativeWorkSeason CreativeWorkSeries DataCatalog DataDownload DataFeed Dataset DiscussionForumPosting Episode FAQPage Game HowTo HowToDirection HowToSection HowToStep HowToTip ImageObject LearningResource MediaObject Message MobileApplication Movie MusicPlaylist MusicRecording NewsArticle Photograph PodcastEpisode PodcastSeries ProfilePage QAPage Question Quiz Recipe Review ScholarlyArticle SearchResultsPage SiteNavigationElement SocialMediaPosting SoftwareApplication TVEpisode TVSeries TechArticle VacationRental VideoGame VideoObject WebApplication WebPage WebPageElement WebSite";
const EVENT_TYPES: &str =
    "BroadcastEvent BusinessEvent EducationEvent Festival MusicEvent SportsEvent TheaterEvent";
const PRODUCT_TYPES: &str = "Car IndividualProduct ProductGroup ProductModel";
const RATING_TYPES: &str = "AggregateRating EmployerAggregateRating Rating";
const TYPES_WITHOUT_PROPERTIES: &str =
    "AlignmentObject BedDetails Certification ContactPoint CreditCard DefinedRegion EducationalOccupationalCredential EntryPoint GeoCoordinates GeoShape InteractionCounter JobPosting LocationFeatureSpecification MathSolver MemberProgram MemberProgramTier MerchantReturnPolicy MerchantReturnPolicySeasonalOverride MonetaryAmount NutritionInformation OccupationalExperienceRequirements OfferShippingDetails OpeningHoursSpecification PeopleAudience PostalAddress PriceSpecification PropertyValue QuantitativeValue ServicePeriod ShippingConditions ShippingDeliveryTime ShippingRateSettings ShippingService SpeakableSpecification Thing UnitPriceSpecification";

#[derive(Clone, Copy)]
enum PropertyRule {
    Scalar(&'static str),
    Entity(&'static str, &'static str),
}

const EMPTY_RULES: &[PropertyRule] = &[];
const AGGREGATE_OFFER_RULES: &[PropertyRule] = &[PropertyRule::Entity("offers", "Offer")];
const BRAND_RULES: &[PropertyRule] = &[PropertyRule::Scalar("name")];
const BREADCRUMB_LIST_RULES: &[PropertyRule] =
    &[PropertyRule::Entity("itemListElement", "ListItem")];
const CREATIVE_WORK_RULES: &[PropertyRule] = &[
    PropertyRule::Scalar("genre"),
    PropertyRule::Scalar("dateCreated"),
    PropertyRule::Scalar("dateModified"),
    PropertyRule::Scalar("datePublished"),
    PropertyRule::Scalar("expires"),
    PropertyRule::Scalar("learningResourceType"),
    PropertyRule::Scalar("educationalLevel"),
    PropertyRule::Scalar("educationalUse"),
    PropertyRule::Scalar("interactivityType"),
    PropertyRule::Entity("aggregateRating", "AggregateRating"),
    PropertyRule::Entity("potentialAction", ACTION_TYPES),
    PropertyRule::Entity("publisher", ORGANIZATION_TYPES),
];
const EVENT_RULES: &[PropertyRule] = &[
    PropertyRule::Scalar("startDate"),
    PropertyRule::Scalar("endDate"),
    PropertyRule::Scalar("previousStartDate"),
    PropertyRule::Entity("aggregateRating", "AggregateRating"),
    PropertyRule::Entity("offers", "AggregateOffer Offer"),
];
const ITEM_LIST_RULES: &[PropertyRule] = &[PropertyRule::Entity("itemListElement", "ListItem")];
const LIST_ITEM_RULES: &[PropertyRule] = &[PropertyRule::Entity("item", "")];
const OFFER_RULES: &[PropertyRule] = &[PropertyRule::Entity("seller", ORGANIZATION_TYPES)];
const ORGANIZATION_RULES: &[PropertyRule] = &[
    PropertyRule::Scalar("name"),
    PropertyRule::Scalar("legalName"),
    PropertyRule::Scalar("foundingDate"),
    PropertyRule::Scalar("dissolutionDate"),
    PropertyRule::Entity("aggregateRating", "AggregateRating"),
    PropertyRule::Entity("brand", "Brand"),
];
const PLACE_RULES: &[PropertyRule] = &[PropertyRule::Entity("aggregateRating", "AggregateRating")];
const PRODUCT_RULES: &[PropertyRule] = &[
    PropertyRule::Scalar("name"),
    PropertyRule::Scalar("sku"),
    PropertyRule::Scalar("mpn"),
    PropertyRule::Scalar("gtin"),
    PropertyRule::Scalar("gtin8"),
    PropertyRule::Scalar("gtin12"),
    PropertyRule::Scalar("gtin13"),
    PropertyRule::Scalar("gtin14"),
    PropertyRule::Scalar("productID"),
    PropertyRule::Scalar("productGroupID"),
    PropertyRule::Scalar("asin"),
    PropertyRule::Scalar("model"),
    PropertyRule::Scalar("category"),
    PropertyRule::Scalar("color"),
    PropertyRule::Scalar("material"),
    PropertyRule::Scalar("pattern"),
    PropertyRule::Scalar("size"),
    PropertyRule::Scalar("productionDate"),
    PropertyRule::Scalar("releaseDate"),
    PropertyRule::Entity("brand", "Brand Organization"),
    PropertyRule::Entity("manufacturer", ORGANIZATION_TYPES),
    PropertyRule::Entity("offers", "Offer AggregateOffer"),
    PropertyRule::Entity("aggregateRating", "AggregateRating"),
];
const SERVICE_RULES: &[PropertyRule] = &[
    PropertyRule::Scalar("name"),
    PropertyRule::Scalar("serviceType"),
    PropertyRule::Scalar("category"),
    PropertyRule::Entity("provider", ORGANIZATION_TYPES),
    PropertyRule::Entity("areaServed", PLACE_TYPES),
    PropertyRule::Entity("offers", "AggregateOffer Offer"),
    PropertyRule::Entity("aggregateRating", "AggregateRating"),
];
const OFFER_CATALOG_RULES: &[PropertyRule] = &[
    PropertyRule::Scalar("name"),
    PropertyRule::Entity("itemListElement", ""),
];

fn listed(types: &str, entity_type: &str) -> bool {
    types
        .split_ascii_whitespace()
        .any(|candidate| candidate == entity_type)
}

fn entity_rules(entity_type: &str) -> Option<&'static [PropertyRule]> {
    match entity_type {
        "AggregateOffer" => Some(AGGREGATE_OFFER_RULES),
        "Brand" => Some(BRAND_RULES),
        "BreadcrumbList" => Some(BREADCRUMB_LIST_RULES),
        "CreativeWork" => Some(CREATIVE_WORK_RULES),
        "Event" => Some(EVENT_RULES),
        "ItemList" => Some(ITEM_LIST_RULES),
        "ListItem" => Some(LIST_ITEM_RULES),
        "Offer" => Some(OFFER_RULES),
        "Organization" => Some(ORGANIZATION_RULES),
        "Person" => Some(EMPTY_RULES),
        "Place" => Some(PLACE_RULES),
        "Product" => Some(PRODUCT_RULES),
        "Service" => Some(SERVICE_RULES),
        "OfferCatalog" => Some(OFFER_CATALOG_RULES),
        _ if listed(ACTION_TYPES, entity_type) => Some(EMPTY_RULES),
        _ if listed(CREATIVE_WORK_TYPES, entity_type) => Some(CREATIVE_WORK_RULES),
        _ if listed(EVENT_TYPES, entity_type) => Some(EVENT_RULES),
        _ if listed(ORGANIZATION_TYPES, entity_type) => Some(ORGANIZATION_RULES),
        _ if listed(PLACE_TYPES, entity_type) => Some(PLACE_RULES),
        _ if listed(PRODUCT_TYPES, entity_type) => Some(PRODUCT_RULES),
        _ if listed(RATING_TYPES, entity_type) => Some(EMPTY_RULES),
        _ if listed(TYPES_WITHOUT_PROPERTIES, entity_type) => Some(EMPTY_RULES),
        _ => None,
    }
}

fn is_scalar(value: &Value<'_>) -> bool {
    matches!(
        value,
        Value::String(_)
            | Value::Static(
                StaticNode::Null
                    | StaticNode::Bool(_)
                    | StaticNode::I64(_)
                    | StaticNode::U64(_)
                    | StaticNode::F64(_)
            )
    )
}

fn sanitize_scalar<'v>(value: &Value<'v>) -> Option<Value<'v>> {
    if is_scalar(value) || as_array(value).is_some_and(|items| items.iter().all(is_scalar)) {
        Some(value.clone())
    } else {
        None
    }
}

fn normalize_entity_type(entity_type: &str) -> &str {
    entity_type
        .strip_prefix("https://schema.org/")
        .or_else(|| entity_type.strip_prefix("http://schema.org/"))
        .unwrap_or(entity_type)
}

fn entity_types(value: Option<&Value<'_>>, allowed_types: Option<&str>) -> Vec<String> {
    let values: Vec<&str> = match value {
        Some(Value::String(value)) => vec![value.as_ref()],
        Some(Value::Array(values)) => values.iter().filter_map(as_str).collect(),
        _ => Vec::new(),
    };
    values
        .into_iter()
        .map(normalize_entity_type)
        .filter(|entity_type| entity_rules(entity_type).is_some())
        .filter(|entity_type| {
            allowed_types.is_none_or(|allowed| allowed.is_empty() || listed(allowed, entity_type))
        })
        .map(str::to_string)
        .collect()
}

fn owned_string<'v>(value: String) -> Value<'v> {
    Value::String(Cow::Owned(value))
}

fn sanitize_entity_value<'v>(value: &Value<'v>, allowed_types: &str) -> Option<Value<'v>> {
    if let Some(items) = as_array(value) {
        let sanitized: Vec<Value<'v>> = items
            .iter()
            .filter_map(|item| sanitize_entity(item, Some(allowed_types)))
            .collect();
        return (!sanitized.is_empty()).then_some(Value::Array(Box::new(sanitized)));
    }
    sanitize_entity(value, Some(allowed_types))
}

fn sanitize_entity<'v>(value: &Value<'v>, allowed_types: Option<&str>) -> Option<Value<'v>> {
    let object = as_object(value)?;
    let type_value = object.get("@type");
    let types = entity_types(type_value, allowed_types);
    if types.is_empty() {
        return None;
    }

    let mut result = Object::default();
    let sanitized_type = if matches!(type_value, Some(Value::String(_))) {
        owned_string(types[0].clone())
    } else {
        Value::Array(Box::new(types.iter().cloned().map(owned_string).collect()))
    };
    result.insert(key("@type"), sanitized_type);

    if let Some(id) = object.get("@id").and_then(sanitize_scalar) {
        result.insert(key("@id"), id);
    }
    for property in TYPE_INDEPENDENT_LEAF_PROPERTIES.split_ascii_whitespace() {
        if let Some(value) = object.get(property).and_then(sanitize_scalar) {
            result.insert(Cow::Borrowed(property), value);
        }
    }

    for entity_type in &types {
        for rule in entity_rules(entity_type).unwrap_or(EMPTY_RULES) {
            match *rule {
                PropertyRule::Scalar(property) => {
                    if let Some(value) = object.get(property).and_then(sanitize_scalar) {
                        result.insert(Cow::Borrowed(property), value);
                    }
                }
                PropertyRule::Entity(property, allowed_types) => {
                    if let Some(value) = object
                        .get(property)
                        .and_then(|value| sanitize_entity_value(value, allowed_types))
                    {
                        result.insert(Cow::Borrowed(property), value);
                    }
                }
            }
        }
    }

    Some(Value::Object(Box::new(result)))
}

fn is_schema_context(value: &Value<'_>) -> bool {
    matches!(
        as_str(value),
        Some(
            "https://schema.org"
                | "https://schema.org/"
                | "http://schema.org"
                | "http://schema.org/"
        )
    )
}

fn sanitize_root<'v>(value: &Value<'v>) -> Option<Value<'v>> {
    let object = as_object(value)?;
    if !object.get("@context").is_some_and(is_schema_context) {
        return None;
    }

    if let Some(Value::Object(mut entity)) = sanitize_entity(value, None) {
        entity.insert(key("@context"), owned_string(SCHEMA_CONTEXT.to_string()));
        return Some(Value::Object(entity));
    }

    let graph = object.get("@graph").and_then(as_array)?;
    let entities: Vec<Value<'v>> = graph
        .iter()
        .filter_map(|entity| sanitize_entity(entity, None))
        .collect();
    if entities.is_empty() {
        return None;
    }
    let mut result = Object::default();
    result.insert(key("@context"), owned_string(SCHEMA_CONTEXT.to_string()));
    result.insert(key("@graph"), Value::Array(Box::new(entities)));
    Some(Value::Object(Box::new(result)))
}

fn sanitize_json_ld<'v>(value: &Value<'v>) -> Option<Value<'v>> {
    if value.encode().len() > MAX_JSON_LD_LENGTH {
        return None;
    }

    let sanitized = if let Some(roots) = as_array(value) {
        if roots.is_empty() {
            return None;
        }
        let roots: Option<Vec<Value<'v>>> = roots.iter().map(sanitize_root).collect();
        Value::Array(Box::new(roots?))
    } else {
        sanitize_root(value)?
    };

    (sanitized.encode().len() <= MAX_JSON_LD_OUTPUT_LENGTH).then_some(sanitized)
}

pub(crate) fn scrub_json_ld_payload<'v>(data: &mut Object<'v>) -> bool {
    let sanitized = data.get("payload").and_then(sanitize_json_ld);
    match sanitized {
        Some(sanitized) if data.get("payload") == Some(&sanitized) => false,
        Some(sanitized) => {
            data.insert(key("payload"), sanitized);
            true
        }
        None => data.remove("payload").is_some(),
    }
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;
    use crate::json::{as_object_mut, parse_untrusted};

    fn scrub(payload: serde_json::Value) -> serde_json::Value {
        let mut bytes =
            serde_json::to_vec(&json!({ "tag": "$json_ld", "payload": payload })).unwrap();
        let mut data = parse_untrusted(&mut bytes).unwrap();
        assert!(scrub_json_ld_payload(as_object_mut(&mut data).unwrap()));
        serde_json::from_str(&data.encode()).unwrap()
    }

    #[test]
    fn matches_posthog_js_json_ld_sanitization() {
        let cases = [
            (
                json!({
                    "@context": "https://schema.org",
                    "@type": "Product",
                    "@id": "https://example.com/products/camera",
                    "name": "Camera",
                    "email": "viewer@example.com",
                    "offers": {
                        "@type": "Offer",
                        "price": 100,
                        "seller": { "@type": "Person", "name": "Example Viewer" }
                    }
                }),
                json!({
                    "tag": "$json_ld",
                    "payload": {
                        "@context": "https://schema.org",
                        "@type": "Product",
                        "@id": "https://example.com/products/camera",
                        "name": "Camera",
                        "offers": { "@type": "Offer", "price": 100 }
                    }
                }),
            ),
            (
                json!({
                    "@context": "http://schema.org/",
                    "@graph": [
                        {
                            "@type": "WebSite",
                            "datePublished": "2026-08-25",
                            "email": "viewer@example.com",
                            "potentialAction": {
                                "@type": "SearchAction",
                                "actionStatus": "https://schema.org/PotentialActionStatus",
                                "target": "https://example.com/search?q=private"
                            }
                        },
                        { "@type": "PrivateType", "email": "viewer@example.com" }
                    ]
                }),
                json!({
                    "tag": "$json_ld",
                    "payload": {
                        "@context": "https://schema.org",
                        "@graph": [{
                            "@type": "WebSite",
                            "datePublished": "2026-08-25",
                            "potentialAction": {
                                "@type": "SearchAction",
                                "actionStatus": "https://schema.org/PotentialActionStatus"
                            }
                        }]
                    }
                }),
            ),
            (
                json!({
                    "@context": "https://schema.org",
                    "@type": ["https://schema.org/Product", "Car", "PrivateType", 42],
                    "name": ["Camera", 2, true, null],
                    "color": ["black", { "value": "private" }]
                }),
                json!({
                    "tag": "$json_ld",
                    "payload": {
                        "@context": "https://schema.org",
                        "@type": ["Product", "Car"],
                        "name": ["Camera", 2, true, null]
                    }
                }),
            ),
            (
                json!({ "@context": "https://example.com", "@type": "Product", "name": "Camera" }),
                json!({ "tag": "$json_ld" }),
            ),
            (
                json!({ "@context": "https://schema.org", "@type": "Product", "name": "x".repeat(20_001) }),
                json!({ "tag": "$json_ld" }),
            ),
        ];

        for (payload, expected) in cases {
            assert_eq!(scrub(payload), expected);
        }
    }
}
