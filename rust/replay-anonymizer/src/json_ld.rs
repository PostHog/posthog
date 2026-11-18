use std::borrow::Cow;
use std::collections::HashSet;

use simd_json::borrowed::{Object, Value};
use simd_json::prelude::Writable;
use simd_json::StaticNode;

use crate::json::{as_array, as_object, as_str, key};

// Keep this policy aligned with posthog-js/packages/browser/src/extensions/replay/external/json-ld.ts.
const MAX_JSON_LD_LENGTH: usize = 100_000;
const MAX_JSON_LD_OUTPUT_LENGTH: usize = 20_000;
const MAX_JSON_LD_TYPE_LENGTH: usize = 100;
const MAX_JSON_LD_TYPES: usize = 20;
const MAX_JSON_LD_NODES: usize = 2_048;
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

#[derive(Clone, Copy)]
enum PropertyRule {
    Scalar(&'static str),
    Entity(&'static str, &'static str),
}

struct SanitizationBudget {
    remaining_nodes: usize,
    exceeded: bool,
}

impl SanitizationBudget {
    fn take_node(&mut self) -> bool {
        if self.remaining_nodes == 0 {
            self.exceeded = true;
            return false;
        }
        self.remaining_nodes -= 1;
        true
    }
}

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
        "Place" => Some(PLACE_RULES),
        "Product" => Some(PRODUCT_RULES),
        "Service" => Some(SERVICE_RULES),
        "OfferCatalog" => Some(OFFER_CATALOG_RULES),
        _ if listed(CREATIVE_WORK_TYPES, entity_type) => Some(CREATIVE_WORK_RULES),
        _ if listed(EVENT_TYPES, entity_type) => Some(EVENT_RULES),
        _ if listed(ORGANIZATION_TYPES, entity_type) => Some(ORGANIZATION_RULES),
        _ if listed(PLACE_TYPES, entity_type) => Some(PLACE_RULES),
        _ if listed(PRODUCT_TYPES, entity_type) => Some(PRODUCT_RULES),
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

fn has_uri_scheme(value: &str) -> bool {
    let Some(separator_index) = value.find(':') else {
        return false;
    };
    let mut scheme = value[..separator_index].chars();
    scheme
        .next()
        .is_some_and(|first| first.is_ascii_alphabetic())
        && scheme.all(|character| {
            character.is_ascii_alphanumeric() || matches!(character, '+' | '.' | '-')
        })
}

fn sanitize_id<'v>(value: &Value<'_>) -> Option<Value<'v>> {
    let id = as_str(value)?.trim();
    let hash_index = id.find('#');
    let fragment = hash_index.map_or(id, |index| &id[index + 1..]);
    if fragment.is_empty()
        || (hash_index.is_none() && (has_uri_scheme(id) || id.contains('/') || id.contains('?')))
    {
        return None;
    }
    Some(owned_string(fragment.to_string()))
}

fn normalize_entity_type(entity_type: &str) -> &str {
    entity_type
        .strip_prefix("https://schema.org/")
        .or_else(|| entity_type.strip_prefix("http://schema.org/"))
        .unwrap_or(entity_type)
}

// Unknown types keep their name in the output, so the shape rule keeps free text such as an email out of the `@type` slot.
fn is_schema_term(entity_type: &str) -> bool {
    entity_type.bytes().all(|byte| byte.is_ascii_alphanumeric())
        && entity_type.bytes().any(|byte| byte.is_ascii_alphabetic())
}

fn entity_types(value: Option<&Value<'_>>) -> Vec<String> {
    let values: Vec<&str> = match value {
        Some(Value::String(value)) => vec![value.as_ref()],
        Some(Value::Array(values)) => values.iter().filter_map(as_str).collect(),
        _ => Vec::new(),
    };
    let mut seen = HashSet::new();
    values
        .into_iter()
        .map(normalize_entity_type)
        .filter(|entity_type| {
            is_schema_term(entity_type)
                && entity_type.encode_utf16().count() <= MAX_JSON_LD_TYPE_LENGTH
        })
        .filter(|entity_type| seen.insert(*entity_type))
        .take(MAX_JSON_LD_TYPES)
        .map(str::to_string)
        .collect()
}

fn owned_string<'v>(value: String) -> Value<'v> {
    Value::String(Cow::Owned(value))
}

fn sanitize_entity_value<'v>(
    value: &Value<'v>,
    allowed_types: &str,
    budget: &mut SanitizationBudget,
) -> Option<Value<'v>> {
    if let Some(items) = as_array(value) {
        let sanitized: Vec<Value<'v>> = items
            .iter()
            .filter_map(|item| sanitize_entity_value(item, allowed_types, budget))
            .collect();
        return (!sanitized.is_empty()).then_some(Value::Array(Box::new(sanitized)));
    }
    sanitize_entity(value, Some(allowed_types), budget)
}

fn sanitize_entity<'v>(
    value: &Value<'v>,
    allowed_types: Option<&str>,
    budget: &mut SanitizationBudget,
) -> Option<Value<'v>> {
    let object = as_object(value)?;
    if !budget.take_node() {
        return None;
    }
    let type_value = object.get("@type");
    let types = entity_types(type_value);

    let mut result = Object::default();
    if !types.is_empty() {
        let sanitized_type = if matches!(type_value, Some(Value::String(_))) {
            owned_string(types[0].clone())
        } else {
            Value::Array(Box::new(types.iter().cloned().map(owned_string).collect()))
        };
        result.insert(key("@type"), sanitized_type);
    }

    if let Some(id) = object.get("@id").and_then(sanitize_id) {
        result.insert(key("@id"), id);
    }
    for property in TYPE_INDEPENDENT_LEAF_PROPERTIES.split_ascii_whitespace() {
        if let Some(value) = object.get(property).and_then(sanitize_scalar) {
            result.insert(Cow::Borrowed(property), value);
        }
    }

    for entity_type in &types {
        if allowed_types.is_some_and(|allowed| !allowed.is_empty() && !listed(allowed, entity_type))
        {
            continue;
        }
        let Some(rules) = entity_rules(entity_type) else {
            continue;
        };
        for rule in rules {
            match *rule {
                PropertyRule::Scalar(property) => {
                    if let Some(value) = object.get(property).and_then(sanitize_scalar) {
                        result.insert(Cow::Borrowed(property), value);
                    }
                }
                PropertyRule::Entity(property, allowed_types) => {
                    if let Some(value) = object
                        .get(property)
                        .and_then(|value| sanitize_entity_value(value, allowed_types, budget))
                    {
                        result.insert(Cow::Borrowed(property), value);
                    }
                }
            }
        }
    }

    if let Some(graph) = object
        .get("@graph")
        .and_then(|value| sanitize_entity_value(value, "", budget))
    {
        result.insert(key("@graph"), graph);
    }

    (!result.is_empty()).then_some(Value::Object(Box::new(result)))
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

fn sanitize_root<'v>(value: &Value<'v>, budget: &mut SanitizationBudget) -> Option<Value<'v>> {
    let object = as_object(value)?;
    if !object.get("@context").is_some_and(is_schema_context) {
        return None;
    }

    let Value::Object(mut entity) = sanitize_entity(value, None, budget)? else {
        return None;
    };
    entity.insert(key("@context"), owned_string(SCHEMA_CONTEXT.to_string()));
    Some(Value::Object(entity))
}

fn sanitize_json_ld<'v>(value: &Value<'v>) -> Option<Value<'v>> {
    if value.encode().encode_utf16().count() > MAX_JSON_LD_LENGTH {
        return None;
    }

    let mut budget = SanitizationBudget {
        remaining_nodes: MAX_JSON_LD_NODES,
        exceeded: false,
    };
    let sanitized = if let Some(roots) = as_array(value) {
        if roots.is_empty() {
            return None;
        }
        let roots: Option<Vec<Value<'v>>> = roots
            .iter()
            .map(|root| sanitize_root(root, &mut budget))
            .collect();
        Value::Array(Box::new(roots?))
    } else {
        sanitize_root(value, &mut budget)?
    };

    if budget.exceeded {
        return None;
    }

    (sanitized.encode().encode_utf16().count() <= MAX_JSON_LD_OUTPUT_LENGTH).then_some(sanitized)
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
        scrub_json_ld_payload(as_object_mut(&mut data).unwrap());
        serde_json::from_str(&data.encode()).unwrap()
    }

    #[test]
    fn matches_posthog_js_json_ld_sanitization() {
        let contract: serde_json::Value = serde_json::from_str(include_str!(
            "../tests/fixtures/json-ld-sanitization-v1.json"
        ))
        .unwrap();
        assert_eq!(contract["schemaVersion"], 1);
        assert_eq!(
            contract["limits"]["typePattern"], "^[A-Za-z0-9]*[A-Za-z][A-Za-z0-9]*$",
            "is_schema_term mirrors the published type pattern"
        );

        // The server has no DOM, so every case runs as if each `@id` fragment is captured.
        for case in contract["cases"].as_array().unwrap() {
            let expected = match &case["expected"] {
                serde_json::Value::Null => json!({ "tag": "$json_ld" }),
                expected => json!({ "tag": "$json_ld", "payload": expected }),
            };
            assert_eq!(scrub(case["input"].clone()), expected, "{}", case["name"]);
        }

        for type_set in contract["typeSets"].as_array().unwrap() {
            for entity_type in type_set["types"].as_array().unwrap() {
                let input = json!({
                    "@context": "https://schema.org",
                    "@type": entity_type,
                });
                assert_eq!(
                    scrub(input.clone()),
                    json!({ "tag": "$json_ld", "payload": input }),
                    "{}: {}",
                    type_set["name"],
                    entity_type
                );
            }
        }

        for entity_type in contract["rejectedTypes"].as_array().unwrap() {
            let input = json!({
                "@context": "https://schema.org",
                "@type": entity_type,
            });
            assert_eq!(scrub(input), json!({ "tag": "$json_ld" }), "{entity_type}");
        }
    }

    #[test]
    fn keeps_nested_entity_arrays() {
        let input = json!({
            "@context": "https://schema.org",
            "@type": "Product",
            "offers": [
                [{ "@type": "Offer", "price": 100, "email": "private@example.com" }],
                "private"
            ]
        });
        assert_eq!(
            scrub(input),
            json!({
                "tag": "$json_ld",
                "payload": {
                    "@context": "https://schema.org",
                    "@type": "Product",
                    "offers": [[{ "@type": "Offer", "price": 100 }]]
                }
            })
        );
    }

    #[test]
    fn enforces_posthog_js_json_ld_limits() {
        let contract: serde_json::Value = serde_json::from_str(include_str!(
            "../tests/fixtures/json-ld-sanitization-v1.json"
        ))
        .unwrap();
        let max_type_length = contract["limits"]["maxTypeLength"].as_u64().unwrap() as usize;
        let max_types = contract["limits"]["maxTypes"].as_u64().unwrap() as usize;
        let max_nodes = contract["limits"]["maxNodes"].as_u64().unwrap() as usize;
        let max_source_length = contract["limits"]["maxSourceLength"].as_u64().unwrap() as usize;
        let max_payload_length = contract["limits"]["maxPayloadLength"].as_u64().unwrap() as usize;

        let root = |entity_type: String, name: Option<String>| {
            json!({
                "@context": "https://schema.org",
                "@type": entity_type,
                "name": name
            })
        };
        let without_name = |value: serde_json::Value| {
            let mut value = value;
            value.as_object_mut().unwrap().remove("name");
            value
        };

        let type_at_limit = without_name(root("T".repeat(max_type_length), None));
        assert_eq!(
            scrub(type_at_limit.clone()),
            json!({ "tag": "$json_ld", "payload": type_at_limit })
        );
        assert_eq!(
            scrub(without_name(root("T".repeat(max_type_length + 1), None))),
            json!({ "tag": "$json_ld" })
        );

        let types: Vec<String> = (0..max_types).map(|index| format!("Type{index}")).collect();
        let type_input = json!({
            "@context": "https://schema.org",
            "@type": types,
        });
        assert_eq!(
            scrub(type_input.clone()),
            json!({ "tag": "$json_ld", "payload": type_input })
        );
        let mut types_over_limit = types.clone();
        types_over_limit.push("TypeOverLimit".to_string());
        assert_eq!(
            scrub(json!({
                "@context": "https://schema.org",
                "@type": types_over_limit,
            })),
            json!({
                "tag": "$json_ld",
                "payload": {
                    "@context": "https://schema.org",
                    "@type": types,
                }
            })
        );

        let root_with_graph = |graph_size: usize| {
            json!({
                "@context": "https://schema.org",
                "@type": "Thing",
                "@graph": vec![json!({}); graph_size],
            })
        };
        assert_eq!(
            scrub(root_with_graph(max_nodes - 1)),
            json!({
                "tag": "$json_ld",
                "payload": {
                    "@context": "https://schema.org",
                    "@type": "Thing",
                }
            })
        );
        assert_eq!(
            scrub(root_with_graph(max_nodes)),
            json!({ "tag": "$json_ld" })
        );

        let empty_source = json!({
            "@context": "https://schema.org",
            "@type": "Product",
            "private": ""
        });
        let empty_source_length = serde_json::to_string(&empty_source)
            .unwrap()
            .encode_utf16()
            .count();
        let source_at_limit = json!({
            "@context": "https://schema.org",
            "@type": "Product",
            "private": "x".repeat(max_source_length - empty_source_length)
        });
        assert_eq!(
            scrub(source_at_limit),
            json!({
                "tag": "$json_ld",
                "payload": { "@context": "https://schema.org", "@type": "Product" }
            })
        );
        let source_over_limit = json!({
            "@context": "https://schema.org",
            "@type": "Product",
            "private": "x".repeat(max_source_length - empty_source_length + 1)
        });
        assert_eq!(scrub(source_over_limit), json!({ "tag": "$json_ld" }));

        let empty_payload = root("Product".to_string(), Some(String::new()));
        let empty_payload_length = serde_json::to_string(&empty_payload)
            .unwrap()
            .encode_utf16()
            .count();
        let payload_at_limit = root(
            "Product".to_string(),
            Some("x".repeat(max_payload_length - empty_payload_length)),
        );
        assert_eq!(
            scrub(payload_at_limit.clone()),
            json!({ "tag": "$json_ld", "payload": payload_at_limit })
        );
        assert_eq!(
            scrub(root(
                "Product".to_string(),
                Some("x".repeat(max_payload_length - empty_payload_length + 1))
            )),
            json!({ "tag": "$json_ld" })
        );
    }
}
