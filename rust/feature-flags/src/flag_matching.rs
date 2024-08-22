use crate::{
    api::FlagError,
    database::Client as DatabaseClient,
    flag_definitions::{FeatureFlag, FlagGroupType, PropertyFilter},
    property_matching::match_property,
};
use serde_json::Value;
use sha1::{Digest, Sha1};
use std::{collections::HashMap, fmt::Write, sync::Arc};

#[derive(Debug, PartialEq, Eq)]
pub struct FeatureFlagMatch {
    pub matches: bool,
    pub variant: Option<String>,
    //reason
    //condition_index
    //payload
}

#[derive(Debug, sqlx::FromRow)]
pub struct Person {
    pub properties: sqlx::types::Json<HashMap<String, Value>>,
}

// TODO: Rework FeatureFlagMatcher - python has a pretty awkward interface, where we pass in all flags, and then again
// the flag to match. I don't think there's any reason anymore to store the flags in the matcher, since we can just
// pass the flag to match directly to the get_match method. This will also make the matcher more stateless.
// Potentially, we could also make the matcher a long-lived object, with caching for group keys and such.
// It just takes in the flag and distinct_id and returns the match...
// Or, make this fully stateless
// and have a separate cache struct for caching group keys, cohort definitions, etc. - and check size, if we can keep it in memory
// for all teams. If not, we can have a LRU cache, or a cache that stores only the most recent N keys.
// But, this can be a future refactor, for now just focusing on getting the basic matcher working, write lots and lots of tests
// and then we can easily refactor stuff around.
// #[derive(Debug)]
pub struct FeatureFlagMatcher {
    // pub flags: Vec<FeatureFlag>,
    pub distinct_id: String,
    pub database_client: Option<Arc<dyn DatabaseClient + Send + Sync>>,
    // TODO do I need cached_properties, or do I get them from the request?
    // like, in python I get them from the request.  Hmm.  Let me try that.
    // OH, or is this the FlagMatcherCache.  Yeah, so this is the flag matcher cache
    cached_properties: Option<HashMap<String, Value>>,
    person_property_overrides: Option<HashMap<String, Value>>,
    // TODO handle group properties
    // group_property_overrides: Option<HashMap<String, HashMap<String, Value>>>,
}

const LONG_SCALE: u64 = 0xfffffffffffffff;

impl FeatureFlagMatcher {
    pub fn new(
        distinct_id: String,
        database_client: Option<Arc<dyn DatabaseClient + Send + Sync>>,
        person_property_overrides: Option<HashMap<String, Value>>,
        // group_property_overrides: Option<HashMap<String, HashMap<String, Value>>>,
    ) -> Self {
        FeatureFlagMatcher {
            // flags,
            distinct_id,
            database_client,
            cached_properties: None,
            person_property_overrides,
            // group_property_overrides,
        }
    }

    pub async fn get_match(&mut self, feature_flag: &FeatureFlag) -> FeatureFlagMatch {
        if self.hashed_identifier(feature_flag).is_none() {
            return FeatureFlagMatch {
                matches: false,
                variant: None,
            };
        }

        // TODO: super groups for early access
        // TODO: Variant overrides condition sort

        for (index, condition) in feature_flag.get_conditions().iter().enumerate() {
            let (is_match, _evaluation_reason) = self
                .is_condition_match(feature_flag, condition, index)
                .await;

            if is_match {
                // TODO: This is a bit awkward, we should handle overrides only when variants exist.
                let variant = match condition.variant.clone() {
                    Some(variant_override) => {
                        if feature_flag
                            .get_variants()
                            .iter()
                            .any(|v| v.key == variant_override)
                        {
                            Some(variant_override)
                        } else {
                            self.get_matching_variant(feature_flag)
                        }
                    }
                    None => self.get_matching_variant(feature_flag),
                };

                // let payload = self.get_matching_payload(is_match, variant, feature_flag);
                return FeatureFlagMatch {
                    matches: true,
                    variant,
                };
            }
        }
        FeatureFlagMatch {
            matches: false,
            variant: None,
        }
    }

    fn check_rollout(&self, feature_flag: &FeatureFlag, rollout_percentage: f64) -> (bool, String) {
        if rollout_percentage == 100.0
            || self.get_hash(feature_flag, "") <= (rollout_percentage / 100.0)
        {
            (true, "CONDITION_MATCH".to_string())
        } else {
            (false, "OUT_OF_ROLLOUT_BOUND".to_string())
        }
    }

    // TODO: Making all this mutable just to store a cached value is annoying. Can I refactor this to be non-mutable?
    // Leaning a bit more towards a separate cache store for this.
    pub async fn is_condition_match(
        &mut self,
        feature_flag: &FeatureFlag,
        condition: &FlagGroupType,
        _index: usize,
    ) -> (bool, String) {
        let rollout_percentage = condition.rollout_percentage.unwrap_or(100.0);
        if let Some(properties) = &condition.properties {
            if properties.is_empty() {
                return self.check_rollout(feature_flag, rollout_percentage);
            }

            let target_properties = self.get_target_properties(feature_flag, properties).await;

            if !self.all_properties_match(properties, &target_properties) {
                return (false, "NO_CONDITION_MATCH".to_string());
            }
        }

        self.check_rollout(feature_flag, rollout_percentage)
    }

    async fn get_target_properties(
        &mut self,
        feature_flag: &FeatureFlag,
        properties: &Vec<PropertyFilter>,
    ) -> HashMap<String, Value> {
        self.get_person_properties(feature_flag.team_id, properties)
            .await
        // TODO handle group properties, will go something like this
        // if let Some(group_index) = feature_flag.get_group_type_index() {
        //     self.get_group_properties(feature_flag.team_id, group_index, properties)
        // } else {
        //     self.get_person_properties(feature_flag.team_id, properties)
        //         .await
        // }
    }

    async fn get_person_properties(
        &mut self,
        team_id: i32,
        properties: &[PropertyFilter],
    ) -> HashMap<String, Value> {
        if let Some(person_overrides) = &self.person_property_overrides {
            // Check if all required properties are present in the overrides
            // and none of them are of type "cohort"
            let all_properties_valid = properties
                .iter()
                .all(|prop| person_overrides.contains_key(&prop.key) && prop.prop_type != "cohort");

            if all_properties_valid {
                return person_overrides.clone();
            }
        }

        // If overrides are not present, don't contain all required properties,
        // or contain a cohort property, fall back to getting properties from cache or DB
        self.get_person_properties_from_cache_or_db(team_id, self.distinct_id.clone())
            .await
            .unwrap_or_default()
    }

    fn all_properties_match(
        &self,
        condition_properties: &[PropertyFilter],
        target_properties: &HashMap<String, Value>,
    ) -> bool {
        condition_properties
            .iter()
            .all(|property| match_property(property, target_properties, false).unwrap_or(false))
    }

    pub fn hashed_identifier(&self, feature_flag: &FeatureFlag) -> Option<String> {
        if feature_flag.get_group_type_index().is_none() {
            // TODO: Use hash key overrides for experience continuity
            Some(self.distinct_id.clone())
        } else {
            // TODO: Handle getting group key
            Some("".to_string())
        }
    }

    /// This function takes a identifier and a feature flag key and returns a float between 0 and 1.
    /// Given the same identifier and key, it'll always return the same float. These floats are
    /// uniformly distributed between 0 and 1, so if we want to show this feature to 20% of traffic
    /// we can do _hash(key, identifier) < 0.2
    pub fn get_hash(&self, feature_flag: &FeatureFlag, salt: &str) -> f64 {
        // check if hashed_identifier is None
        let hashed_identifier = self
            .hashed_identifier(feature_flag)
            .expect("hashed_identifier is None when computing hash");
        let hash_key = format!("{}.{}{}", feature_flag.key, hashed_identifier, salt);
        let mut hasher = Sha1::new();
        hasher.update(hash_key.as_bytes());
        let result = hasher.finalize();
        // :TRICKY: Convert the first 15 characters of the digest to a hexadecimal string
        let hex_str: String = result.iter().fold(String::new(), |mut acc, byte| {
            let _ = write!(acc, "{:02x}", byte);
            acc
        })[..15]
            .to_string();
        let hash_val = u64::from_str_radix(&hex_str, 16).unwrap();

        hash_val as f64 / LONG_SCALE as f64
    }

    pub fn get_matching_variant(&self, feature_flag: &FeatureFlag) -> Option<String> {
        let hash = self.get_hash(feature_flag, "variant");
        let mut total_percentage = 0.0;

        for variant in feature_flag.get_variants() {
            total_percentage += variant.rollout_percentage / 100.0;
            if hash < total_percentage {
                return Some(variant.key.clone());
            }
        }
        None
    }

    pub async fn get_person_properties_from_cache_or_db(
        &mut self,
        team_id: i32,
        distinct_id: String,
    ) -> Result<HashMap<String, Value>, FlagError> {
        // TODO: Do we even need to cache here anymore?
        // Depends on how often we're calling this function
        // to match all flags for a single person

        // TODO which of these properties do we need to cache?
        if let Some(cached_props) = self.cached_properties.clone() {
            // TODO: Maybe we don't want to copy around all user properties, this will by far be the largest chunk
            // of data we're copying around. Can we work with references here?
            // Worst case, just use a Rc.
            return Ok(cached_props);
        }

        if self.database_client.is_none() {
            return Err(FlagError::DatabaseUnavailable);
        }

        let mut conn = self
            .database_client
            .as_ref()
            .expect("client should exist here")
            .get_connection()
            .await?;

        let query = r#"
            SELECT "posthog_person"."properties" 
            FROM "posthog_person"
            INNER JOIN "posthog_persondistinctid" ON ("posthog_person"."id" = "posthog_persondistinctid"."person_id")
            WHERE ("posthog_persondistinctid"."distinct_id" = $1
                    AND "posthog_persondistinctid"."team_id" = $2
                    AND "posthog_person"."team_id" = $3)
            LIMIT 1;
        "#;

        let row = sqlx::query_as::<_, Person>(query)
            .bind(&distinct_id)
            .bind(team_id)
            .bind(team_id)
            .fetch_optional(&mut *conn)
            .await?;

        let props = match row {
            Some(row) => row.properties.0,
            None => HashMap::new(),
        };

        self.cached_properties = Some(props.clone());

        Ok(props)
    }

    // async fn get_group_properties_from_cache_or_db(
    //     &self,
    //     team_id: i32,
    //     group_index: usize,
    //     properties: &Vec<PropertyFilter>,
    // ) -> HashMap<String, Value> {
    //     todo!()
    // }
}

#[cfg(test)]
mod tests {

    use serde_json::json;

    use super::*;
    use crate::test_utils::{insert_new_team_in_pg, insert_person_for_team_in_pg, setup_pg_client};

    #[tokio::test]
    async fn test_fetch_properties_from_pg_to_match() {
        let client = setup_pg_client(None).await;

        let team = insert_new_team_in_pg(client.clone())
            .await
            .expect("Failed to insert team in pg");

        let distinct_id = "user_distinct_id".to_string();
        insert_person_for_team_in_pg(client.clone(), team.id, distinct_id.clone(), None)
            .await
            .expect("Failed to insert person");

        let not_matching_distinct_id = "not_matching_distinct_id".to_string();
        insert_person_for_team_in_pg(
            client.clone(),
            team.id,
            not_matching_distinct_id.clone(),
            Some(json!({ "email": "a@x.com"})),
        )
        .await
        .expect("Failed to insert person");

        let flag = serde_json::from_value(json!(
            {
                "id": 1,
                "team_id": team.id,
                "name": "flag1",
                "key": "flag1",
                "filters": {
                    "groups": [
                        {
                            "properties": [
                                {
                                    "key": "email",
                                    "value": "a@b.com",
                                    "type": "person"
                                }
                            ],
                            "rollout_percentage": 100
                        }
                    ]
                }
            }
        ))
        .unwrap();

        let mut matcher = FeatureFlagMatcher::new(distinct_id, Some(client.clone()), None);
        let match_result = matcher.get_match(&flag).await;
        assert_eq!(match_result.matches, true);
        assert_eq!(match_result.variant, None);

        // property value is different
        let mut matcher =
            FeatureFlagMatcher::new(not_matching_distinct_id, Some(client.clone()), None);
        let match_result = matcher.get_match(&flag).await;
        assert_eq!(match_result.matches, false);
        assert_eq!(match_result.variant, None);

        // person does not exist
        let mut matcher =
            FeatureFlagMatcher::new("other_distinct_id".to_string(), Some(client.clone()), None);
        let match_result = matcher.get_match(&flag).await;
        assert_eq!(match_result.matches, false);
        assert_eq!(match_result.variant, None);
    }
}
