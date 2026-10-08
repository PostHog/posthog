//! Checks against a live ClickHouse, with the VM as the oracle, that `properties` built from
//! trim-quotes columns answers exact equalities like the blob, except for the named residuals and
//! the rows the ambiguity probe sends back to the blob.

#![cfg(feature = "ch-test-support")]

use std::collections::{BTreeMap, BTreeSet};

use chrono_tz::UTC;
use clickhouse::Row;
use cohort_core::events::CohortStreamEvent;
use cohort_core::filters::{CohortId, TeamFilters, TeamFiltersBuilder, TeamId};
use cohort_core::hogvm::analysis::GlobalsPlan;
use cohort_core::hogvm::{build_behavioral_globals, evaluate_detailed, EvalOutcome, GlobalsBuild};
use cohort_seeder::clickhouse::client::build_client;
use cohort_seeder::clickhouse::sql::{ambiguous_values_sql, columns_object_expr};
use cohort_seeder::clickhouse::ClickHouseClient;
use cohort_seeder::config::Config;
use cohort_seeder::domain::{
    ActiveConditions, ChunkProjection, ColumnBackedKeys, ColumnPlan, ConditionAnalyses,
    ConditionHash, Lookback, MaterializedColumns, PinnedCondition, PropertiesSource,
    PropertiesSourcing,
};
use envconfig::Envconfig;
use serde::Deserialize;
use serde_json::{json, Value};

const DATABASE: &str = "seeder_materialized_properties";
const EVENT: &str = "$pageview";
const URL: &str = "$current_url";
const URL_COLUMN: &str = "mat_$current_url";
/// The materializer sanitizes column names, so only the key is hostile.
const ODD: &str = "quote' \"key\\?";
const ODD_COLUMN: &str = "mat_quote___key__";
const PERSON: &str = r#"{"plan":"pro"}"#;

const LITERALS: &[&str] = &[
    "https://example.com/",
    "https://example.com/p?q=1",
    "a\"b",
    "a\\b",
    "tab\there",
    "é😀",
    "quote' OR 1 = 1 --",
    "{not json",
    "2024-01-01",
    "slash/key",
];

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
enum Residual {
    /// Every column stores `''` while `serde_json` reads the blob.
    BlobClickHouseCannotParse,
    /// The column holds the first value, `serde_json` the last.
    RepeatedKey,
    /// Comes back typed and too deep for `serde_json`.
    StringHoldingDeepJson,
    /// The blob fails to evaluate while the columns still build an object.
    UnreadableBlob,
}

impl Residual {
    const fn divergence(self) -> Divergence {
        match self {
            Self::UnreadableBlob => Divergence::OverCount,
            Self::BlobClickHouseCannotParse | Self::StringHoldingDeepJson | Self::RepeatedKey => {
                Divergence::UnderCount
            }
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
enum Divergence {
    OverCount,
    UnderCount,
}

impl Divergence {
    const fn between(from_blob: bool, from_columns: bool) -> Option<Self> {
        match (from_blob, from_columns) {
            (false, true) => Some(Self::OverCount),
            (true, false) => Some(Self::UnderCount),
            (true, true) | (false, false) => None,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Expect {
    Same,
    /// A column reads as `false`, so the scan keeps the blob for the whole chunk.
    Ambiguous,
    Residual(Residual),
}

struct Case {
    blob: String,
    expect: Expect,
}

impl Case {
    fn exact(blob: impl Into<String>) -> Self {
        Self {
            blob: blob.into(),
            expect: Expect::Same,
        }
    }

    fn ambiguous(blob: impl Into<String>) -> Self {
        Self {
            blob: blob.into(),
            expect: Expect::Ambiguous,
        }
    }

    fn residual(blob: impl Into<String>, residual: Residual) -> Self {
        Self {
            blob: blob.into(),
            expect: Expect::Residual(residual),
        }
    }
}

fn corpus() -> Vec<Case> {
    let mut cases: Vec<Case> = [
        r#"{}"#,
        r#"{"other":"https://example.com/"}"#,
        r#"{"$current_url":null}"#,
        r#"{"$current_url":true}"#,
        r#"{"$current_url":5}"#,
        r#"{"$current_url":5.0}"#,
        r#"{"$current_url":-0.0}"#,
        r#"{"$current_url":1e3}"#,
        r#"{"$current_url":["https://example.com/"]}"#,
        r#"{"$current_url":{"https://example.com/":1}}"#,
        r#"{"$current_url":{"__hogDateTime__":true,"dt":1704067200,"zone":"UTC"}}"#,
        r#"{"$current_url":{"__hogDate__":true,"year":2024,"month":1,"day":1}}"#,
        r#"{"$current_url":""}"#,
        r#"{"$current_url":"5"}"#,
        r#"{"$current_url":"5.0"}"#,
        r#"{"$current_url":"1e3"}"#,
        r#"{"$current_url":"true"}"#,
        r#"{"$current_url":"TRUE"}"#,
        r#"{"$current_url":"null"}"#,
        r#"{"$current_url":"{}"}"#,
        r#"{"$current_url":"[1]"}"#,
        r#"{"$current_url":" 5"}"#,
        r#"{"$current_url":"https:\/\/example.com\/"}"#,
        r#"{"$current_url":"https://example.com/"}"#,
        r#"{ "$current_url" : "https://example.com/" , "other" : 1 }"#,
        r#"{"nested":{"$current_url":"https://example.com/"}}"#,
        r#""https://example.com/""#,
        r#"null"#,
        r#""#,
    ]
    .into_iter()
    .map(Case::exact)
    .collect();
    cases.extend(
        [r#"["https://example.com/"]"#, r#"{not json"#]
            .map(|blob| Case::residual(blob, Residual::UnreadableBlob)),
    );
    for literal in LITERALS {
        let escaped = literal
            .encode_utf16()
            .map(|unit| format!("\\u{unit:04x}"))
            .collect::<String>();
        cases.extend([
            Case::exact(json!({ URL: literal }).to_string()),
            Case::exact(json!({ ODD: literal }).to_string()),
            Case::exact(json!({ URL: literal, ODD: literal, "pad": "x" }).to_string()),
            Case::exact(format!(r#"{{"{URL}":"{escaped}"}}"#)),
        ]);
    }
    cases.extend([
        Case::ambiguous(r#"{"$current_url":false}"#),
        Case::ambiguous(r#"{"$current_url":"false"}"#),
        Case::ambiguous(r#"{"$current_url":" false "}"#),
        Case::ambiguous(json!({ URL: "https://example.com/", ODD: "false" }).to_string()),
        Case::residual(
            r#"{"$current_url":"elsewhere","$current_url":"https://example.com/"}"#,
            Residual::RepeatedKey,
        ),
        Case::residual(
            r#"{"$current_url":"https://example.com/","n":18446744073709551616}"#,
            Residual::BlobClickHouseCannotParse,
        ),
        Case::residual(
            json!({
                URL: "https://example.com/",
                ODD: format!("{}{}", "[".repeat(200), "]".repeat(200)),
            })
            .to_string(),
            Residual::StringHoldingDeepJson,
        ),
    ]);
    cases
}

#[derive(Row, Deserialize)]
struct Rebuilt {
    seq: u32,
    properties: String,
    ambiguous: bool,
}

#[tokio::test]
async fn columns_answer_every_exact_equality_like_the_blob_but_the_named_residuals() {
    let (filters, conditions) = catalog();
    let columns = column_backed_properties(&filters, &conditions);
    let programs = conditions
        .iter()
        .map(|condition| {
            filters
                .by_condition_to_program
                .get(&condition.hash.as_bytes())
                .expect("the catalog loads every condition's program")
                .tokens()
                .to_vec()
        })
        .collect::<Vec<_>>();
    let corpus = corpus();
    let rebuilt = rebuild_all(&corpus, &columns).await;

    assert_eq!(
        corpus
            .iter()
            .zip(&rebuilt)
            .filter(|(_, row)| row.ambiguous)
            .map(|(case, _)| case.blob.as_str())
            .collect::<Vec<_>>(),
        corpus
            .iter()
            .filter(|case| case.expect == Expect::Ambiguous)
            .map(|case| case.blob.as_str())
            .collect::<Vec<_>>(),
        "the probe flagged other rows than those whose columns read as false"
    );

    for (
        case,
        Rebuilt {
            properties: rebuilt,
            ..
        },
    ) in corpus.iter().zip(&rebuilt)
    {
        match serde_json::from_str::<Value>(rebuilt) {
            Ok(Value::Object(object)) => assert_eq!(
                object.keys().map(String::as_str).collect::<Vec<_>>(),
                [URL, ODD],
                "{} rebuilt as {rebuilt}",
                case.blob
            ),
            Ok(other) => panic!("{} rebuilt as a non-object {other}", case.blob),
            Err(error) => assert_eq!(
                case.expect,
                Expect::Residual(Residual::StringHoldingDeepJson),
                "{} rebuilt as {rebuilt}, which does not parse: {error}",
                case.blob
            ),
        }
    }

    let divergences: BTreeMap<usize, BTreeSet<Divergence>> = corpus
        .iter()
        .zip(&rebuilt)
        .enumerate()
        .filter(|(_, (_, row))| !row.ambiguous)
        .filter_map(|(index, (case, row))| {
            let found = programs
                .iter()
                .filter_map(|program| {
                    Divergence::between(
                        program_matches(program, &case.blob),
                        program_matches(program, &row.properties),
                    )
                })
                .collect::<BTreeSet<_>>();
            (!found.is_empty()).then_some((index, found))
        })
        .collect();

    let expected: BTreeMap<usize, BTreeSet<Divergence>> = corpus
        .iter()
        .enumerate()
        .filter_map(|(index, case)| {
            let Expect::Residual(residual) = case.expect else {
                return None;
            };
            Some((index, BTreeSet::from([residual.divergence()])))
        })
        .collect();
    let describe = |map: &BTreeMap<usize, BTreeSet<Divergence>>| {
        map.iter()
            .map(|(index, directions)| format!("{} {directions:?}", corpus[*index].blob))
            .collect::<Vec<_>>()
    };
    assert_eq!(
        describe(&divergences),
        describe(&expected),
        "the column form diverged from the blob somewhere other than the named residuals"
    );
}

fn catalog() -> (TeamFilters, Vec<PinnedCondition>) {
    let mut builder = TeamFiltersBuilder::default();
    let mut conditions = Vec::new();
    let equalities = [URL, ODD].into_iter().flat_map(|key| {
        LITERALS.iter().map(move |literal| {
            json!([
                "_H",
                1,
                32,
                EVENT,
                32,
                "event",
                1,
                1,
                11,
                32,
                literal,
                32,
                key,
                32,
                "properties",
                1,
                2,
                11,
                3,
                2
            ])
        })
    });
    let with_person = json!([
        "_H",
        1,
        32,
        EVENT,
        32,
        "event",
        1,
        1,
        11,
        32,
        "https://example.com/",
        32,
        URL,
        32,
        "properties",
        1,
        2,
        11,
        32,
        "pro",
        32,
        "plan",
        32,
        "properties",
        32,
        "person",
        1,
        3,
        11,
        4,
        2,
        3,
        2
    ]);
    let programs = equalities.chain([with_person]);
    for (index, bytecode) in programs.enumerate() {
        let hash = format!("{index:016}");
        let cohort = CohortId(i32::try_from(index).expect("the catalog is small") + 1);
        builder
            .add_cohort(
                cohort,
                TeamId(2),
                &json!({
                    "properties": { "type": "AND", "values": [{
                        "type": "behavioral",
                        "value": "performed_event",
                        "key": EVENT,
                        "conditionHash": hash,
                        "time_value": 7,
                        "time_interval": "day",
                        "bytecode": bytecode,
                    }]}
                }),
            )
            .expect("the test catalog parses");
        conditions.push(PinnedCondition {
            cohort_id: cohort,
            hash: ConditionHash::parse(&hash).expect("the hash is 16 ASCII bytes"),
            event_name: EVENT.to_owned(),
            lookback: Lookback::SlidingDays(7),
        });
    }
    (builder.freeze(UTC), conditions)
}

fn column_backed_properties(
    filters: &TeamFilters,
    conditions: &[PinnedCondition],
) -> ColumnBackedKeys {
    let analyses = ConditionAnalyses::build(conditions, filters);
    let active = ActiveConditions::new(conditions.iter().map(|condition| condition.hash));
    let columns: MaterializedColumns = [(URL, URL_COLUMN), (ODD, ODD_COLUMN)].into_iter().collect();
    let sourcing = analyses
        .projection(&active)
        .source_properties(&analyses.column_exact_keys(&active), &columns);
    let PropertiesSourcing::Upgradable(upgrade) = sourcing else {
        panic!("the analysis did not find every key exact: {sourcing:?}");
    };
    match upgrade.accept().into_projection() {
        ChunkProjection::Projected(ColumnPlan {
            properties: PropertiesSource::Columns(columns),
            ..
        }) => columns,
        other => panic!("an accepted upgrade returned {other:?}"),
    }
}

async fn rebuild_all(corpus: &[Case], columns: &ColumnBackedKeys) -> Vec<Rebuilt> {
    let admin = connect(None);
    for statement in [
        format!("DROP DATABASE IF EXISTS {DATABASE}"),
        format!("CREATE DATABASE {DATABASE}"),
        format!(
            "CREATE TABLE {DATABASE}.events (seq UInt32, properties String, `{URL_COLUMN}` String DEFAULT {}, `{ODD_COLUMN}` String DEFAULT {}) ENGINE = MergeTree ORDER BY seq",
            trim_quotes_extraction(URL),
            trim_quotes_extraction(ODD),
        ),
    ] {
        admin
            .query(&statement)
            .execute()
            .await
            .unwrap_or_else(|error| panic!("{error}\n{statement}"));
    }
    let client = connect(Some(DATABASE));
    client
        .query("INSERT INTO events (seq, properties) SELECT seq, blobs[seq] FROM (SELECT ? AS blobs, arrayJoin(arrayEnumerate(blobs)) AS seq)")
        .bind(corpus.iter().map(|case| case.blob.as_str()).collect::<Vec<_>>())
        .execute()
        .await
        .expect("the corpus inserts");

    let sql = format!(
        "SELECT seq, {} AS properties, {} AS ambiguous FROM events AS e ORDER BY seq",
        columns_object_expr(columns),
        ambiguous_values_sql(columns),
    );
    assert!(
        !sql.contains("e.properties"),
        "the column form reads the blob: {sql}"
    );
    let rows = client
        .query(&sql)
        .fetch_all::<Rebuilt>()
        .await
        .unwrap_or_else(|error| panic!("the column form failed: {error}\n{sql}"));
    assert_eq!(rows.len(), corpus.len(), "a row went missing: {sql}");
    for (position, row) in rows.iter().enumerate() {
        assert_eq!(row.seq as usize, position + 1, "rows arrived out of order");
    }
    rows
}

/// The materializer's expression, with `?` doubled for the client's binds.
fn trim_quotes_extraction(key: &str) -> String {
    let escaped = key
        .replace('\\', "\\\\")
        .replace('\'', "\\'")
        .replace('?', "??");
    format!("replaceRegexpAll(JSONExtractRaw(properties, '{escaped}'), '^\"|\"$', '')")
}

fn connect(database: Option<&str>) -> ClickHouseClient {
    let mut config = Config::init_from_env().expect("the seeder config falls back to its defaults");
    if let Some(database) = database {
        config.clickhouse_database = database.to_owned();
    }
    build_client(&config).expect("the default ClickHouse client builds")
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
        person_properties: Some(PERSON.to_owned()),
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
