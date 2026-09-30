//! Checks against a live ClickHouse that a behavioral scan's row filter admits every row the
//! condition's program matches, with the VM as the oracle, and that the materialized-column lookup
//! accepts only columns holding the same values.

#![cfg(feature = "ch-test-support")]

use std::collections::BTreeSet;

use chrono_tz::UTC;
use clickhouse::Row;
use cohort_core::events::CohortStreamEvent;
use cohort_core::filters::{CohortId, TeamFilters, TeamFiltersBuilder, TeamId};
use cohort_core::hogvm::analysis::GlobalsPlan;
use cohort_core::hogvm::{build_behavioral_globals, evaluate_detailed, EvalOutcome, GlobalsBuild};
use cohort_seeder::clickhouse::client::build_client;
use cohort_seeder::clickhouse::materialized::MaterializedColumns;
use cohort_seeder::clickhouse::sql::row_filter_sql;
use cohort_seeder::clickhouse::ClickHouseClient;
use cohort_seeder::config::Config;
use cohort_seeder::domain::{
    ActiveConditions, ConditionAnalyses, ConditionHash, EventNameSet, Lookback, PinnedCondition,
};
use envconfig::Envconfig;
use serde::Deserialize;
use serde_json::{json, Value};

const HASH: &str = "aaaaaaaaaaaaaaaa";
const EVENT: &str = "$feature_flag_called";
const KEY: &str = "$feature_flag";

const VALUES: &[&str] = &[
    "my-flag",
    "true",
    "TRUE",
    "false",
    "",
    "2024-01-01",
    "2024-01-01T00:00:00Z",
    "a\"b",
    "a\\b",
    "tab\there",
    "é😀",
    "quote' OR 1 = 1 --",
    "why?fields",
    "{not json",
];

/// No blob repeats a key: ClickHouse reads the first value and `serde_json` the last, and stored
/// event properties never repeat one.
const FIXED_BLOBS: &[&str] = &[
    r#"{}"#,
    r#"{"other":"my-flag"}"#,
    r#"{"$feature_flag":"another-flag"}"#,
    r#"{"$feature_flag":"MY-FLAG"}"#,
    r#"{"$feature_flag":null}"#,
    r#"{"$feature_flag":true}"#,
    r#"{"$feature_flag":false}"#,
    r#"{"$feature_flag":5}"#,
    r#"{"$feature_flag":5.0}"#,
    r#"{"$feature_flag":["my-flag"]}"#,
    r#"{"$feature_flag":{"my-flag":1}}"#,
    r#"{"$feature_flag":{"__hogDateTime__":true,"dt":1704067200,"zone":"UTC"}}"#,
    r#"{"$feature_flag":{"__hogDate__":true,"year":2024,"month":1,"day":1}}"#,
    r#"{ "$feature_flag" : "my-flag" , "other" : 1 }"#,
    r#"{"nested":{"$feature_flag":"my-flag"}}"#,
    r#"["my-flag"]"#,
    r#""my-flag""#,
    r#"null"#,
    r#""#,
    r#"{not json"#,
];

#[derive(Row, Deserialize)]
struct Admitted {
    index: u32,
    admitted: bool,
}

#[tokio::test]
async fn the_row_filter_admits_every_row_the_program_matches() {
    let client = connect(None);
    for value in VALUES {
        let (filters, program) = condition(value);
        let predicate = rendered_predicate(&filters, &MaterializedColumns::default());
        let blobs = blobs_for(value);
        let admitted = admit_all(&client, &predicate, &blobs).await;
        for (blob, admitted) in blobs.iter().zip(admitted) {
            if program_matches(&program, blob) {
                assert!(
                    admitted,
                    "value {value:?}: the program matches {blob:?} but the filter dropped it\n{predicate}"
                );
            }
        }
    }
}

#[tokio::test]
async fn the_row_filter_drops_rows_no_program_can_match() {
    let client = connect(None);
    let (filters, _) = condition("my-flag");
    let predicate = rendered_predicate(&filters, &MaterializedColumns::default());
    let dropped = [
        r#"{}"#,
        r#"{"other":"my-flag"}"#,
        r#"{"$feature_flag":"another-flag"}"#,
        r#"{"$feature_flag":"MY-FLAG"}"#,
        r#"{"$feature_flag":null}"#,
        r#"{"$feature_flag":5}"#,
        r#"{"$feature_flag":["my-flag"]}"#,
        r#"{"nested":{"$feature_flag":"my-flag"}}"#,
    ];
    let admitted = admit_all(&client, &predicate, &dropped).await;
    assert_eq!(admitted, vec![false; dropped.len()], "{predicate}");
}

/// Only a live server shows how ClickHouse formats the stored default expression.
#[tokio::test]
async fn the_lookup_accepts_only_trim_quotes_columns_on_both_tables() {
    const DATABASE: &str = "seeder_materialized_lookup";
    let admin = connect(None);
    for statement in [
        format!("DROP DATABASE IF EXISTS {DATABASE}"),
        format!("CREATE DATABASE {DATABASE}"),
        format!(
            "CREATE TABLE {DATABASE}.sharded_events (\
                properties String, \
                `mat_$feature_flag` String DEFAULT replaceRegexpAll(JSONExtractRaw(properties, '$feature_flag'), '^\"|\"$', ''), \
                mat_typed String DEFAULT JSONExtract(properties, 'typed', 'String'), \
                mat_nullable Nullable(String) DEFAULT JSONExtract(properties, 'nullable', 'Nullable(String)'), \
                `mat_$data_only` String DEFAULT replaceRegexpAll(JSONExtractRaw(properties, '$data_only'), '^\"|\"$', '')\
            ) ENGINE = MergeTree ORDER BY tuple()"
        ),
        format!(
            "CREATE TABLE {DATABASE}.events (\
                properties String, \
                `mat_$feature_flag` String COMMENT 'column_materializer::properties::$feature_flag', \
                mat_typed String, \
                mat_nullable Nullable(String)\
            ) ENGINE = Memory"
        ),
    ] {
        admin
            .query(&statement)
            .execute()
            .await
            .unwrap_or_else(|error| panic!("{error}\n{statement}"));
    }

    let client = connect(Some(DATABASE));
    let keys = BTreeSet::from(["$feature_flag", "typed", "nullable", "$data_only", "absent"]);
    let columns = MaterializedColumns::lookup(&client, &keys)
        .await
        .expect("the lookup reads only system.columns");
    assert_eq!(
        columns.column_for("$feature_flag"),
        Some("mat_$feature_flag")
    );
    for refused in ["typed", "nullable", "$data_only", "absent"] {
        assert_eq!(columns.column_for(refused), None, "{refused}");
    }
}

fn connect(database: Option<&str>) -> ClickHouseClient {
    let mut config = Config::init_from_env().expect("the seeder config falls back to its defaults");
    if let Some(database) = database {
        config.clickhouse_database = database.to_owned();
    }
    build_client(&config).expect("the default ClickHouse client builds")
}

fn condition(value: &str) -> (TeamFilters, Vec<Value>) {
    let mut builder = TeamFiltersBuilder::default();
    builder
        .add_cohort(
            CohortId(1),
            TeamId(2),
            &json!({
                "properties": { "type": "AND", "values": [{
                    "type": "behavioral",
                    "value": "performed_event",
                    "key": EVENT,
                    "conditionHash": HASH,
                    "time_value": 7,
                    "time_interval": "day",
                    "bytecode": [
                        "_H", 1,
                        32, EVENT, 32, "event", 1, 1, 11,
                        32, value, 32, KEY, 32, "properties", 1, 2, 11,
                        3, 2
                    ]
                }]}
            }),
        )
        .unwrap();
    let filters = builder.freeze(UTC);
    let hash = ConditionHash::parse(HASH).unwrap();
    let program = filters
        .by_condition_to_program
        .get(&hash.as_bytes())
        .expect("the catalog loads the condition's program")
        .tokens()
        .to_vec();
    (filters, program)
}

fn rendered_predicate(filters: &TeamFilters, columns: &MaterializedColumns) -> String {
    let hash = ConditionHash::parse(HASH).unwrap();
    let conditions = [PinnedCondition {
        cohort_id: CohortId(1),
        hash,
        event_name: EVENT.to_owned(),
        lookback: Lookback::SlidingDays(7),
    }];
    let analyses = ConditionAnalyses::build(&conditions, filters);
    let row_filter = analyses.row_filter(
        &EventNameSet::new([EVENT.to_owned()]),
        filters,
        &ActiveConditions::new([hash]),
    );
    assert!(
        !row_filter.is_empty(),
        "the condition carries no row filter"
    );
    let predicate = row_filter_sql(&row_filter, columns);
    assert_eq!(predicate.matches("e.properties").count(), 3, "{predicate}");
    predicate
        .replace("e.properties", "blob")
        .replace("e.event", "'$feature_flag_called'")
}

fn blobs_for(value: &str) -> Vec<String> {
    let escaped = value
        .encode_utf16()
        .map(|unit| format!("\\u{unit:04x}"))
        .collect::<String>();
    let mut blobs: Vec<String> = FIXED_BLOBS.iter().map(|blob| (*blob).to_owned()).collect();
    blobs.push(json!({ KEY: value }).to_string());
    blobs.push(format!(r#"{{"{KEY}":"{escaped}"}}"#));
    blobs
}

fn program_matches(program: &[Value], blob: &str) -> bool {
    let event = CohortStreamEvent {
        team_id: 2,
        person_id: "0190c3a5-0000-7000-8000-000000000001".to_owned(),
        distinct_id: "distinct".to_owned(),
        uuid: "0190c3a5-0000-7000-8000-000000000002".to_owned(),
        event: EVENT.to_owned(),
        timestamp: "2024-01-01 00:00:00.000000".to_owned(),
        properties: (!blob.is_empty()).then(|| blob.to_owned()),
        person_properties: None,
        elements_chain: None,
        source_offset: 0,
        source_partition: -1,
        redirected_from: None,
        redirect_hops: 0,
    };
    let Ok(globals) = build_behavioral_globals(&event, GlobalsBuild::whole(GlobalsPlan::FULL))
    else {
        return false;
    };
    matches!(
        evaluate_detailed(program, globals),
        EvalOutcome::Matched(true)
    )
}

async fn admit_all(
    client: &ClickHouseClient,
    predicate: &str,
    blobs: &[impl AsRef<str>],
) -> Vec<bool> {
    let sql = format!(
        "WITH ? AS blobs\nSELECT index, {predicate} AS admitted\nFROM (SELECT arrayJoin(arrayEnumerate(blobs)) AS index, blobs[index] AS blob)\nORDER BY index",
    );
    let owned = blobs
        .iter()
        .map(|blob| blob.as_ref().to_owned())
        .collect::<Vec<_>>();
    let rows = client
        .query(&sql)
        .bind(owned)
        .fetch_all::<Admitted>()
        .await
        .unwrap_or_else(|error| panic!("the row-filter query failed: {error}\n{sql}"));
    assert_eq!(rows.len(), blobs.len(), "a blob went missing: {sql}");
    for (position, row) in rows.iter().enumerate() {
        assert_eq!(
            row.index as usize,
            position + 1,
            "rows arrived out of order: {sql}"
        );
    }
    rows.into_iter().map(|row| row.admitted).collect()
}
