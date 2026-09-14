//! Which relations a statement touches, and which one drives it.
//!
//! sqlparser handles the Django/ORM shapes we see in pg_stat_statements text (`$1`
//! placeholders, `= ANY($1)`, `::jsonb`, quoted identifiers). Text is capped at 10 KiB
//! in `cur_queries` and may be truncated mid-statement, so a regex over the leading
//! keywords is the fallback.

use once_cell::sync::Lazy;
use regex::Regex;
use sqlparser::ast::{
    visit_relations, Delete, FromTable, Insert, ObjectName, Query, SetExpr, Statement, TableFactor,
    TableObject, TableWithJoins, Update,
};
use sqlparser::dialect::PostgreSqlDialect;
use sqlparser::parser::Parser;
use std::ops::ControlFlow;

#[derive(Debug, Default, PartialEq, Eq)]
pub struct Extracted {
    /// The DML target of an INSERT/UPDATE/DELETE.
    pub target: Option<String>,
    /// Relations of the outermost FROM, driving table first, joins after it.
    pub outer: Vec<String>,
    /// Relations only referenced from subqueries or CTEs.
    pub inner: Vec<String>,
    pub parser: &'static str,
    /// `owner='team-x'` from a sqlcommenter-style leading comment.
    pub marker: Option<String>,
}

impl Extracted {
    /// Every relation, most authoritative first, without duplicates.
    pub fn ranked(&self) -> Vec<&str> {
        let mut out: Vec<&str> = Vec::new();
        for t in self
            .target
            .iter()
            .chain(self.outer.iter())
            .chain(self.inner.iter())
        {
            if !out.contains(&t.as_str()) {
                out.push(t);
            }
        }
        out
    }

    /// Only `pg_catalog` / `information_schema` relations: introspection, not workload.
    pub fn catalog_only(&self) -> bool {
        let all = self.ranked();
        !all.is_empty() && all.iter().all(|t| is_catalog(t))
    }
}

pub fn is_catalog(table: &str) -> bool {
    table.starts_with("pg_") || table.starts_with("information_schema.")
}

static MARKER: Lazy<Regex> =
    Lazy::new(|| Regex::new(r#"(?i)/\*.*?\bowner\s*[=:]\s*'?([a-z0-9@_-]+)'?.*?\*/"#).unwrap());
static FALLBACK: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r#"(?i)\b(?:FROM|JOIN|UPDATE|INTO|DELETE\s+FROM)\s+((?:"[^"]+"|[a-z_][a-z0-9_]*)(?:\.(?:"[^"]+"|[a-z_][a-z0-9_]*))?)"#).unwrap()
});
static DML: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r#"(?i)^\s*(?:/\*.*?\*/\s*)*(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+((?:"[^"]+"|[a-z_][a-z0-9_]*)(?:\.(?:"[^"]+"|[a-z_][a-z0-9_]*))?)"#).unwrap()
});

pub fn extract(sql: &str) -> Extracted {
    let marker = MARKER.captures(sql).map(|c| c[1].to_ascii_lowercase());
    let mut ex = match Parser::parse_sql(&PostgreSqlDialect {}, sql) {
        Ok(stmts) if !stmts.is_empty() => from_ast(&stmts[0]),
        _ => from_regex(sql),
    };
    ex.marker = marker;
    ex
}

fn from_ast(stmt: &Statement) -> Extracted {
    let mut ex = Extracted {
        parser: "sqlparser",
        ..Default::default()
    };
    match stmt {
        Statement::Query(q) => outer_from_query(q, &mut ex.outer),
        Statement::Insert(Insert { table, source, .. }) => {
            if let TableObject::TableName(n) = table {
                ex.target = Some(name(n));
            }
            if let Some(q) = source {
                outer_from_query(q, &mut ex.outer);
            }
        }
        Statement::Update(Update { table, from, .. }) => {
            let mut t = Vec::new();
            twj(table, &mut t);
            ex.target = t.into_iter().next();
            if let Some(f) = from {
                for x in from_tables(f) {
                    twj(x, &mut ex.outer);
                }
            }
        }
        Statement::Delete(Delete { from, using, .. }) => {
            let (FromTable::WithFromKeyword(v) | FromTable::WithoutKeyword(v)) = from;
            let mut t = Vec::new();
            for x in v {
                twj(x, &mut t);
            }
            ex.target = t.into_iter().next();
            if let Some(u) = using {
                for x in u {
                    twj(x, &mut ex.outer);
                }
            }
        }
        _ => {}
    }
    let mut all = Vec::new();
    let _: ControlFlow<()> = visit_relations(stmt, |n| {
        all.push(name(n));
        ControlFlow::Continue(())
    });
    for t in all {
        if ex.target.as_deref() != Some(t.as_str())
            && !ex.outer.contains(&t)
            && !ex.inner.contains(&t)
        {
            ex.inner.push(t);
        }
    }
    ex
}

fn from_tables(f: &sqlparser::ast::UpdateTableFromKind) -> &[TableWithJoins] {
    use sqlparser::ast::UpdateTableFromKind::{AfterSet, BeforeSet};
    match f {
        BeforeSet(v) | AfterSet(v) => v,
    }
}

fn outer_from_query(q: &Query, out: &mut Vec<String>) {
    match q.body.as_ref() {
        SetExpr::Select(s) => {
            for f in &s.from {
                twj(f, out);
            }
        }
        SetExpr::Query(inner) => outer_from_query(inner, out),
        SetExpr::SetOperation { left, .. } => {
            if let SetExpr::Select(s) = left.as_ref() {
                for f in &s.from {
                    twj(f, out);
                }
            }
        }
        _ => {}
    }
}

fn twj(t: &TableWithJoins, out: &mut Vec<String>) {
    factor(&t.relation, out);
    for j in &t.joins {
        factor(&j.relation, out);
    }
}

fn factor(f: &TableFactor, out: &mut Vec<String>) {
    if let TableFactor::Table { name: n, .. } = f {
        let n = name(n);
        if !out.contains(&n) {
            out.push(n);
        }
    }
}

/// `"public"."posthog_team"` -> `posthog_team`; `pg_catalog.pg_class` keeps its prefix so
/// catalog queries stay recognisable.
fn name(n: &ObjectName) -> String {
    let parts: Vec<String> =
        n.0.iter()
            .filter_map(|p| p.as_ident())
            .map(|i| i.value.to_ascii_lowercase())
            .collect();
    normalize(&parts.join("."))
}

fn normalize(s: &str) -> String {
    let s = s.replace('"', "");
    match s.rsplit_once('.') {
        Some(("public", table)) => table.to_string(),
        Some(("pg_catalog", table)) => format!("pg_{}", table.trim_start_matches("pg_")),
        _ => s,
    }
}

fn from_regex(sql: &str) -> Extracted {
    let mut ex = Extracted {
        parser: "regex",
        ..Default::default()
    };
    ex.target = DML
        .captures(sql)
        .map(|c| normalize(&c[1].to_ascii_lowercase()));
    for c in FALLBACK.captures_iter(sql) {
        let t = normalize(&c[1].to_ascii_lowercase());
        if ex.target.as_deref() != Some(t.as_str()) && !ex.outer.contains(&t) {
            ex.outer.push(t);
        }
    }
    ex
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ex(sql: &str) -> Extracted {
        extract(sql)
    }

    #[test]
    fn django_select_related_join_keeps_driving_table_first() {
        let e = ex(
            r#"SELECT "posthog_dashboard"."id", "posthog_team"."name" FROM "posthog_dashboard" INNER JOIN "posthog_team" ON ("posthog_dashboard"."team_id" = "posthog_team"."id") WHERE "posthog_dashboard"."id" = $1 LIMIT $2"#,
        );
        assert_eq!(e.parser, "sqlparser");
        assert_eq!(e.outer, vec!["posthog_dashboard", "posthog_team"]);
        assert_eq!(e.target, None);
    }

    #[test]
    fn subquery_tables_rank_after_outer_ones() {
        let e = ex(
            r#"SELECT * FROM "posthog_insight" WHERE "posthog_insight"."team_id" IN (SELECT U0."team_id" FROM "posthog_organizationmembership" U0 WHERE U0."user_id" = $1) AND "posthog_insight"."id" = ANY($2)"#,
        );
        assert_eq!(e.outer, vec!["posthog_insight"]);
        assert_eq!(e.inner, vec!["posthog_organizationmembership"]);
        assert_eq!(
            e.ranked(),
            vec!["posthog_insight", "posthog_organizationmembership"]
        );
    }

    #[test]
    fn dml_target_wins_over_joined_tables() {
        let e = ex(
            r#"UPDATE "posthog_cohort" SET "is_calculating" = $1 FROM "posthog_team" WHERE "posthog_cohort"."team_id" = "posthog_team"."id""#,
        );
        assert_eq!(e.target.as_deref(), Some("posthog_cohort"));
        assert_eq!(e.ranked()[0], "posthog_cohort");
        let e = ex(
            r#"INSERT INTO "posthog_persondistinctid" ("distinct_id", "person_id", "team_id") VALUES ($1, $2, $3) RETURNING "posthog_persondistinctid"."id""#,
        );
        assert_eq!(e.target.as_deref(), Some("posthog_persondistinctid"));
        let e = ex(
            r#"DELETE FROM "posthog_element" USING "posthog_elementgroup" WHERE "posthog_element"."group_id" = "posthog_elementgroup"."id""#,
        );
        assert_eq!(e.target.as_deref(), Some("posthog_element"));
        assert_eq!(e.outer, vec!["posthog_elementgroup"]);
    }

    #[test]
    fn cte_relations_are_inner() {
        let e = ex("WITH recent AS (SELECT id FROM posthog_event WHERE ts > $1) SELECT count(*) FROM posthog_person p JOIN recent r ON r.id = p.id");
        assert_eq!(e.outer, vec!["posthog_person", "recent"]);
        assert_eq!(e.inner, vec!["posthog_event"]);
    }

    #[test]
    fn truncated_text_falls_back_to_regex() {
        let e = ex(
            r#"SELECT "posthog_featureflag"."id" FROM "posthog_featureflag" INNER JOIN "posthog_team" ON ("posthog_featureflag"."team_id" = "posthog_team"."id") WHERE "posthog_featureflag"."key" IN ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $1"#,
        );
        assert_eq!(e.parser, "regex");
        assert_eq!(e.outer, vec!["posthog_featureflag", "posthog_team"]);
        let e = ex(
            r#"UPDATE "posthog_team" SET "updated_at" = $1 WHERE "posthog_team"."id" IN ($1, $2, $3, $"#,
        );
        assert_eq!(e.parser, "regex");
        assert_eq!(e.target.as_deref(), Some("posthog_team"));
    }

    #[test]
    fn schema_prefix_and_catalog_detection() {
        let e = ex(
            r#"SELECT c.relname FROM pg_catalog.pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"#,
        );
        assert!(e.catalog_only());
        let e = ex(r#"SELECT 1 FROM "public"."posthog_team" t, other_schema.audit a"#);
        assert_eq!(e.outer, vec!["posthog_team", "other_schema.audit"]);
        assert!(!e.catalog_only());
        assert!(!ex("SELECT 1").catalog_only());
    }

    #[test]
    fn owner_marker_is_read_from_a_leading_comment() {
        let e = ex(
            "/*owner='team-feature-flags',route='/api/flags'*/ SELECT 1 FROM posthog_featureflag",
        );
        assert_eq!(e.marker.as_deref(), Some("team-feature-flags"));
        assert_eq!(e.outer, vec!["posthog_featureflag"]);
        assert_eq!(ex("SELECT 1 FROM posthog_featureflag").marker, None);
    }
}
