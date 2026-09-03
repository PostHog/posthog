//! Cache builder logic for producing the hypercache flags payload.
//!
//! Rust equivalent of Python's `_get_feature_flags_for_service()` in
//! `products/feature_flags/backend/flags_cache.py`. Reads flags and cohorts from
//! Postgres, computes evaluation metadata (dependency stages via Kahn's algorithm),
//! and produces the `HypercacheFlagsWrapper` JSON payload.

use std::collections::{HashMap, HashSet};

use common_database::PostgresReader;
use common_types::TeamId;

use crate::api::errors::FlagError;
use crate::cohorts::cohort_models::{Cohort, CohortId};
use crate::flags::flag_models::{
    EvaluationMetadata, FeatureFlag, FeatureFlagId, FeatureFlagList, FlagFilters,
    HypercacheFlagsWrapper,
};
use crate::properties::property_models::PropertyFilter;
use crate::utils::graph_utils::{DependencyGraph, DependencyProvider, DependencyType};

/// Maximum BFS depth when resolving transitive cohort-on-cohort dependencies.
/// Matches Python's `_MAX_COHORT_DEPENDENCY_DEPTH`.
const MAX_COHORT_DEPENDENCY_DEPTH: usize = 20;

/// Newtype adapter for `FeatureFlag` that implements `DependencyProvider`,
/// keeping graph-specific trait impls separate from the domain model.
#[derive(Debug, Clone)]
struct FlagNode(FeatureFlag);

impl DependencyProvider for FlagNode {
    type Id = FeatureFlagId;
    type Error = FlagError;

    fn get_id(&self) -> Self::Id {
        self.0.id
    }

    fn extract_dependencies(&self) -> Result<HashSet<Self::Id>, Self::Error> {
        Ok(extract_direct_flag_dependency_ids(&self.0))
    }

    fn dependency_type() -> DependencyType {
        DependencyType::Flag
    }
}

/// Build the full flags cache payload for a team.
pub async fn build_flags_cache(
    pg_reader: PostgresReader,
    team_id: TeamId,
) -> Result<HypercacheFlagsWrapper, FlagError> {
    let mut flags = FeatureFlagList::from_pg(pg_reader.clone(), team_id).await?;
    retain_evaluable_and_referenced_flags(&mut flags);
    let evaluation_metadata = compute_flag_dependencies(&flags)?;
    let cohorts = fetch_referenced_cohorts(pg_reader, team_id, &flags).await?;
    blank_inactive_filters(&mut flags);

    Ok(HypercacheFlagsWrapper {
        flags,
        evaluation_metadata,
        cohorts: Some(cohorts),
    })
}

/// Whether `active`/`deleted` let the matcher evaluate this flag. Anything failing this
/// lands in `filtered_out_flag_ids` before `filters` is read, so its filters cannot
/// affect a response.
///
/// Do not widen this to the rest of that set (survey, evaluation runtime, evaluation
/// contexts): those are request-scoped, so blanking on them would strip targeting that
/// other requests still need.
pub(crate) fn is_evaluable(flag: &FeatureFlag) -> bool {
    flag.active && !flag.deleted
}

/// Keep the flags worth caching: evaluable ones, plus unevaluable ones that another
/// flag's dependency conditions reference — those pre-seed as false in the matcher,
/// so a dependent's `flag_evaluates_to: false` condition still matches.
///
/// Mirrors Python's `_drop_unreferenced_unevaluable_flags()` in
/// `products/feature_flags/backend/flags_cache.py`, where the full rationale lives.
fn retain_evaluable_and_referenced_flags(flags: &mut Vec<FeatureFlag>) {
    let referenced_ids: HashSet<FeatureFlagId> = flags
        .iter()
        .flat_map(active_flag_properties)
        .filter_map(|p| p.get_feature_flag_id())
        .collect();
    flags.retain(|flag| is_evaluable(flag) || referenced_ids.contains(&flag.id));
}

/// Empty the `filters` of flags that can never be evaluated, so the unreachable
/// blob stops occupying Redis, S3, and the service's in-memory cache.
///
/// Mirrors Python's `_blank_inactive_filters()` in
/// `products/feature_flags/backend/flags_cache.py`.
fn blank_inactive_filters(flags: &mut [FeatureFlag]) {
    for flag in flags.iter_mut().filter(|f| !is_evaluable(f)) {
        flag.filters = FlagFilters::default();
    }
}

/// Yields all property filters from an active, non-deleted flag's filter groups.
fn active_flag_properties(flag: &FeatureFlag) -> impl Iterator<Item = &PropertyFilter> {
    let groups = if is_evaluable(flag) {
        flag.filters.groups.as_slice()
    } else {
        &[]
    };
    groups.iter().flat_map(|g| g.properties.iter().flatten())
}

/// Extract direct flag dependency IDs from a single flag's filters.
///
/// Scans `filters.groups[*].properties` for `type == "flag"` properties and
/// parses their `key` as an integer flag ID. Inactive/deleted flags return
/// empty deps to match Python's `_extract_direct_dependency_ids()`.
fn extract_direct_flag_dependency_ids(flag: &FeatureFlag) -> HashSet<FeatureFlagId> {
    active_flag_properties(flag)
        .filter_map(|p| p.get_feature_flag_id())
        .collect()
}

/// Extract cohort IDs directly referenced in active flag filters.
pub fn extract_cohort_ids_from_flag_filters(flags: &[FeatureFlag]) -> HashSet<CohortId> {
    flags
        .iter()
        .flat_map(active_flag_properties)
        .filter_map(|p| p.get_cohort_id())
        .collect()
}

/// Compute flag dependency metadata via the shared `DependencyGraph` framework.
///
/// Produces output identical to Python's `_compute_flag_dependencies()`:
/// - `dependency_stages`: flag IDs grouped by evaluation stage (stage 0 = no deps first),
///   sorted within each stage
/// - `flags_with_missing_deps`: sorted list of flag IDs with missing, cyclic, or
///   transitively broken dependencies
/// - `transitive_deps`: flag ID → set of all transitive dependency flag IDs
pub fn compute_flag_dependencies(flags: &[FeatureFlag]) -> Result<EvaluationMetadata, FlagError> {
    if flags.is_empty() {
        return Ok(EvaluationMetadata::default());
    }

    let original_flag_ids: HashSet<FeatureFlagId> = flags.iter().map(|f| f.id).collect();
    let nodes: Vec<FlagNode> = flags.iter().cloned().map(FlagNode).collect();

    let mut edges: HashMap<FeatureFlagId, HashSet<FeatureFlagId>> =
        HashMap::with_capacity(nodes.len());
    for node in &nodes {
        edges.insert(node.get_id(), node.extract_dependencies()?);
    }

    // Build graph — tolerant of missing deps and cycles.
    // from_nodes → finalize → remove_all_cycles strips cycle participants
    // AND their dependents from the graph.
    let (graph, _errors, mut nodes_with_missing_deps) = DependencyGraph::from_nodes(nodes, &edges)?;

    // Nodes removed during cycle detection are also "missing"
    let remaining_ids: HashSet<FeatureFlagId> = graph.iter_nodes().map(|n| n.get_id()).collect();
    for &id in &original_flag_ids {
        if !remaining_ids.contains(&id) {
            nodes_with_missing_deps.insert(id);
        }
    }

    // Compute evaluation stages, transitive deps, and missing-dep propagation
    let result = graph.compute_evaluation_metadata(&nodes_with_missing_deps)?;

    // Ensure all flags have entries in transitive_deps (cycle participants get empty sets)
    let mut transitive_deps = result.transitive_deps;
    for &fid in &original_flag_ids {
        transitive_deps.entry(fid).or_default();
    }

    Ok(EvaluationMetadata {
        dependency_stages: result.stages,
        flags_with_missing_deps: result.nodes_with_missing_deps,
        transitive_deps,
    })
}

/// Fetch cohort definitions referenced by flags, including transitive
/// cohort-on-cohort dependencies. BFS with depth limit of 20.
///
/// Matches Python's `_get_referenced_cohorts()` + `_load_cohorts_with_deps()`.
pub async fn fetch_referenced_cohorts(
    pg_reader: PostgresReader,
    team_id: TeamId,
    flags: &[FeatureFlag],
) -> Result<Vec<Cohort>, FlagError> {
    let seed_ids = extract_cohort_ids_from_flag_filters(flags);
    if seed_ids.is_empty() {
        return Ok(vec![]);
    }

    load_cohorts_with_deps(pg_reader, team_id, seed_ids).await
}

/// BFS-load cohorts by seed IDs, resolving transitive cohort-on-cohort deps.
///
/// Matches Python's `_load_cohorts_with_deps()` with depth limit of 20.
async fn load_cohorts_with_deps(
    pg_reader: PostgresReader,
    team_id: TeamId,
    seed_ids: HashSet<CohortId>,
) -> Result<Vec<Cohort>, FlagError> {
    let mut all_ids = seed_ids.clone();
    let mut ids_to_load: Vec<CohortId> = seed_ids.into_iter().collect();
    let mut loaded: HashMap<CohortId, Cohort> = HashMap::new();
    let mut depth = 0;

    while !ids_to_load.is_empty() {
        if depth >= MAX_COHORT_DEPENDENCY_DEPTH {
            let sample: Vec<_> = ids_to_load.iter().take(10).copied().collect();
            tracing::warn!(
                depth,
                remaining_count = ids_to_load.len(),
                remaining_sample = ?sample,
                "Cohort dependency depth limit reached"
            );
            break;
        }
        depth += 1;

        let newly_loaded = Cohort::list_by_ids_from_pg(&pg_reader, team_id, &ids_to_load).await?;

        let mut ids_to_load_next: Vec<CohortId> = Vec::new();
        for cohort in newly_loaded {
            let cohort_id = cohort.id;
            match cohort.extract_dependencies() {
                Ok(dep_ids) => {
                    for dep_id in dep_ids {
                        if !all_ids.contains(&dep_id) {
                            all_ids.insert(dep_id);
                            ids_to_load_next.push(dep_id);
                        }
                    }
                }
                Err(e) => {
                    tracing::warn!(
                        cohort_id = cohort_id,
                        team_id = team_id,
                        error = %e,
                        "Failed to extract dependencies for cohort"
                    );
                }
            }
            loaded.insert(cohort_id, cohort);
        }

        ids_to_load = ids_to_load_next;
    }

    let mut cohorts: Vec<Cohort> = loaded.into_values().collect();
    cohorts.sort_by_key(|c| c.id);
    Ok(cohorts)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::flags::flag_models::{FeatureFlagRow, FlagFilters, FlagPropertyGroup};
    use crate::properties::property_models::{OperatorType, PropertyFilter, PropertyType};
    use crate::utils::test_utils::TestContext;
    use test_case::test_case;

    /// A minimal insertable flag row. `id` is a placeholder; the insert helper returns the
    /// row with the real id.
    fn base_flag_row(team_id: i32) -> FeatureFlagRow {
        FeatureFlagRow {
            team_id,
            active: true,
            // `posthog_featureflag.name` is NOT NULL.
            name: Some(String::new()),
            evaluation_runtime: Some("all".to_string()),
            ..Default::default()
        }
    }

    fn make_flag(id: i32, key: &str, active: bool, groups: Vec<FlagPropertyGroup>) -> FeatureFlag {
        FeatureFlag {
            id,
            team_id: 1,
            name: Some(key.to_string()),
            key: key.to_string(),
            filters: FlagFilters {
                groups,
                ..Default::default()
            },
            active,
            ..Default::default()
        }
    }

    fn flag_dep_property(dep_flag_id: i32) -> PropertyFilter {
        PropertyFilter {
            key: dep_flag_id.to_string(),
            value: Some(serde_json::json!("true")),
            operator: Some(OperatorType::Exact),
            prop_type: PropertyType::Flag,
            ..Default::default()
        }
    }

    fn cohort_property(cohort_id: i32) -> PropertyFilter {
        PropertyFilter {
            key: "$cohort".to_string(),
            value: Some(serde_json::json!(cohort_id)),
            operator: Some(OperatorType::Exact),
            prop_type: PropertyType::Cohort,
            ..Default::default()
        }
    }

    fn group_with_properties(props: Vec<PropertyFilter>) -> FlagPropertyGroup {
        FlagPropertyGroup {
            properties: Some(props),
            rollout_percentage: Some(100.0),
            ..Default::default()
        }
    }

    // -------------------------------------------------------------------------
    // extract_direct_flag_dependency_ids tests
    // -------------------------------------------------------------------------

    #[test]
    fn test_extract_deps_no_dependencies() {
        let flag = make_flag(1, "flag_a", true, vec![group_with_properties(vec![])]);
        let deps = extract_direct_flag_dependency_ids(&flag);
        assert!(deps.is_empty());
    }

    #[test]
    fn test_extract_deps_with_flag_dependency() {
        let flag = make_flag(
            1,
            "flag_a",
            true,
            vec![group_with_properties(vec![flag_dep_property(2)])],
        );
        let deps = extract_direct_flag_dependency_ids(&flag);
        assert_eq!(deps, HashSet::from([2]));
    }

    #[test_case(false, false ; "inactive flag")]
    #[test_case(true, true ; "deleted flag")]
    fn test_extract_deps_skipped_flag_returns_empty(active: bool, deleted: bool) {
        let mut flag = make_flag(
            1,
            "flag_a",
            active,
            vec![group_with_properties(vec![flag_dep_property(2)])],
        );
        flag.deleted = deleted;
        let deps = extract_direct_flag_dependency_ids(&flag);
        assert!(deps.is_empty());
    }

    // -------------------------------------------------------------------------
    // extract_cohort_ids_from_flag_filters tests
    // -------------------------------------------------------------------------

    #[test]
    fn test_extract_cohort_ids_empty_flags() {
        let ids = extract_cohort_ids_from_flag_filters(&[]);
        assert!(ids.is_empty());
    }

    #[test]
    fn test_extract_cohort_ids_with_cohort_property() {
        let flag = make_flag(
            1,
            "flag_a",
            true,
            vec![group_with_properties(vec![cohort_property(42)])],
        );
        let ids = extract_cohort_ids_from_flag_filters(&[flag]);
        assert_eq!(ids, HashSet::from([42]));
    }

    #[test_case(false, false ; "inactive flag")]
    #[test_case(true, true ; "deleted flag")]
    fn test_extract_cohort_ids_ignores_skipped(active: bool, deleted: bool) {
        let mut flag = make_flag(
            1,
            "flag_a",
            active,
            vec![group_with_properties(vec![cohort_property(42)])],
        );
        flag.deleted = deleted;
        let ids = extract_cohort_ids_from_flag_filters(&[flag]);
        assert!(ids.is_empty());
    }

    #[test]
    fn test_extract_cohort_ids_string_value() {
        let flag = make_flag(
            1,
            "flag_a",
            true,
            vec![group_with_properties(vec![PropertyFilter {
                key: "$cohort".to_string(),
                value: Some(serde_json::json!("42")),
                operator: Some(OperatorType::Exact),
                prop_type: PropertyType::Cohort,
                ..Default::default()
            }])],
        );
        let ids = extract_cohort_ids_from_flag_filters(&[flag]);
        assert_eq!(ids, HashSet::from([42]));
    }

    #[test]
    fn test_extract_cohort_ids_multiple_flags_and_cohorts() {
        let flag1 = make_flag(
            1,
            "flag_a",
            true,
            vec![group_with_properties(vec![cohort_property(10)])],
        );
        let flag2 = make_flag(
            2,
            "flag_b",
            true,
            vec![group_with_properties(vec![
                cohort_property(20),
                cohort_property(30),
            ])],
        );
        let ids = extract_cohort_ids_from_flag_filters(&[flag1, flag2]);
        assert_eq!(ids, HashSet::from([10, 20, 30]));
    }

    // -------------------------------------------------------------------------
    // compute_flag_dependencies tests
    // -------------------------------------------------------------------------

    #[test]
    fn test_compute_deps_empty_flags() {
        let meta = compute_flag_dependencies(&[]).unwrap();
        assert!(meta.dependency_stages.is_empty());
        assert!(meta.flags_with_missing_deps.is_empty());
        assert!(meta.transitive_deps.is_empty());
    }

    #[test]
    fn test_compute_deps_no_dependencies() {
        let flags = vec![
            make_flag(1, "a", true, vec![group_with_properties(vec![])]),
            make_flag(2, "b", true, vec![group_with_properties(vec![])]),
            make_flag(3, "c", true, vec![group_with_properties(vec![])]),
        ];
        let meta = compute_flag_dependencies(&flags).unwrap();

        // All flags in a single stage, sorted
        assert_eq!(meta.dependency_stages.len(), 1);
        assert_eq!(meta.dependency_stages[0], vec![1, 2, 3]);
        assert!(meta.flags_with_missing_deps.is_empty());
        // Each flag has empty transitive deps
        for id in [1, 2, 3] {
            assert!(meta.transitive_deps[&id].is_empty());
        }
    }

    #[test]
    fn test_compute_deps_linear_chain() {
        // C depends on B, B depends on A
        let flags = vec![
            make_flag(1, "a", true, vec![group_with_properties(vec![])]),
            make_flag(
                2,
                "b",
                true,
                vec![group_with_properties(vec![flag_dep_property(1)])],
            ),
            make_flag(
                3,
                "c",
                true,
                vec![group_with_properties(vec![flag_dep_property(2)])],
            ),
        ];
        let meta = compute_flag_dependencies(&flags).unwrap();

        assert_eq!(meta.dependency_stages.len(), 3);
        assert_eq!(meta.dependency_stages[0], vec![1]); // A has no deps
        assert_eq!(meta.dependency_stages[1], vec![2]); // B depends on A
        assert_eq!(meta.dependency_stages[2], vec![3]); // C depends on B
        assert!(meta.flags_with_missing_deps.is_empty());

        // Transitive deps
        assert!(meta.transitive_deps[&1].is_empty());
        assert_eq!(meta.transitive_deps[&2], HashSet::from([1]));
        assert_eq!(meta.transitive_deps[&3], HashSet::from([1, 2]));
    }

    #[test]
    fn test_compute_deps_diamond() {
        // D depends on B and C, B and C both depend on A
        let flags = vec![
            make_flag(1, "a", true, vec![group_with_properties(vec![])]),
            make_flag(
                2,
                "b",
                true,
                vec![group_with_properties(vec![flag_dep_property(1)])],
            ),
            make_flag(
                3,
                "c",
                true,
                vec![group_with_properties(vec![flag_dep_property(1)])],
            ),
            make_flag(
                4,
                "d",
                true,
                vec![group_with_properties(vec![
                    flag_dep_property(2),
                    flag_dep_property(3),
                ])],
            ),
        ];
        let meta = compute_flag_dependencies(&flags).unwrap();

        assert_eq!(meta.dependency_stages.len(), 3);
        assert_eq!(meta.dependency_stages[0], vec![1]);
        assert_eq!(meta.dependency_stages[1], vec![2, 3]); // B and C in same stage, sorted
        assert_eq!(meta.dependency_stages[2], vec![4]);
        assert!(meta.flags_with_missing_deps.is_empty());

        assert_eq!(meta.transitive_deps[&4], HashSet::from([1, 2, 3]));
    }

    #[test]
    fn test_compute_deps_missing_dependency() {
        // Flag 1 depends on flag 99 which doesn't exist
        let flags = vec![
            make_flag(
                1,
                "a",
                true,
                vec![group_with_properties(vec![flag_dep_property(99)])],
            ),
            make_flag(2, "b", true, vec![group_with_properties(vec![])]),
        ];
        let meta = compute_flag_dependencies(&flags).unwrap();

        // Both flags still appear in stages (flag 1 has in_degree 0 because
        // dep 99 is unknown, so the edge is ignored for in_degree counting)
        assert_eq!(meta.dependency_stages.len(), 1);
        assert_eq!(meta.dependency_stages[0], vec![1, 2]);
        assert_eq!(meta.flags_with_missing_deps, vec![1]);
    }

    #[test]
    fn test_compute_deps_cycle_detection() {
        // A depends on B, B depends on A
        let flags = vec![
            make_flag(
                1,
                "a",
                true,
                vec![group_with_properties(vec![flag_dep_property(2)])],
            ),
            make_flag(
                2,
                "b",
                true,
                vec![group_with_properties(vec![flag_dep_property(1)])],
            ),
        ];
        let meta = compute_flag_dependencies(&flags).unwrap();

        // Cyclic flags are NOT in any stage
        assert!(meta.dependency_stages.is_empty());
        // Both flags are marked as having missing deps (cycled)
        assert_eq!(meta.flags_with_missing_deps, vec![1, 2]);
    }

    #[test]
    fn test_compute_deps_cycle_with_independent_flags() {
        // Flags 1 and 2 form a cycle; flag 3 is independent
        let flags = vec![
            make_flag(
                1,
                "a",
                true,
                vec![group_with_properties(vec![flag_dep_property(2)])],
            ),
            make_flag(
                2,
                "b",
                true,
                vec![group_with_properties(vec![flag_dep_property(1)])],
            ),
            make_flag(3, "c", true, vec![group_with_properties(vec![])]),
        ];
        let meta = compute_flag_dependencies(&flags).unwrap();

        // Only flag 3 appears in stages
        assert_eq!(meta.dependency_stages.len(), 1);
        assert_eq!(meta.dependency_stages[0], vec![3]);
        assert_eq!(meta.flags_with_missing_deps, vec![1, 2]);
    }

    #[test]
    fn test_compute_deps_transitive_missing_propagation() {
        // A is fine, B depends on A, C depends on B and on 99 (missing)
        // D depends on C, so D should also be flagged
        let flags = vec![
            make_flag(1, "a", true, vec![group_with_properties(vec![])]),
            make_flag(
                2,
                "b",
                true,
                vec![group_with_properties(vec![flag_dep_property(1)])],
            ),
            make_flag(
                3,
                "c",
                true,
                vec![group_with_properties(vec![
                    flag_dep_property(2),
                    flag_dep_property(99),
                ])],
            ),
            make_flag(
                4,
                "d",
                true,
                vec![group_with_properties(vec![flag_dep_property(3)])],
            ),
        ];
        let meta = compute_flag_dependencies(&flags).unwrap();

        // Stages: A (0), B (1), C (2), D (3)
        assert_eq!(meta.dependency_stages.len(), 4);
        // C and D are flagged as having missing deps
        assert_eq!(meta.flags_with_missing_deps, vec![3, 4]);
    }

    #[test]
    fn test_compute_deps_transitive_deps_string_keys_in_serialization() {
        // Verify that serialization uses string keys (matching Python)
        let flags = vec![
            make_flag(1, "a", true, vec![group_with_properties(vec![])]),
            make_flag(
                2,
                "b",
                true,
                vec![group_with_properties(vec![flag_dep_property(1)])],
            ),
        ];
        let meta = compute_flag_dependencies(&flags).unwrap();

        // Serialize and verify string keys
        let json = serde_json::to_value(&meta).unwrap();
        let td = json["transitive_deps"].as_object().unwrap();
        assert!(td.contains_key("1"));
        assert!(td.contains_key("2"));
        // Value for flag 2 should be [1]
        assert_eq!(td["2"], serde_json::json!([1]));
    }

    #[test]
    fn test_compute_deps_inactive_flag_deps_ignored() {
        // Flag 2 (inactive) depends on flag 1, but since it's inactive
        // its deps should be empty
        let flags = vec![
            make_flag(1, "a", true, vec![group_with_properties(vec![])]),
            make_flag(
                2,
                "b",
                false,
                vec![group_with_properties(vec![flag_dep_property(1)])],
            ),
        ];
        let meta = compute_flag_dependencies(&flags).unwrap();

        // Both in stage 0 (flag 2's dep on flag 1 is ignored because inactive)
        assert_eq!(meta.dependency_stages.len(), 1);
        assert_eq!(meta.dependency_stages[0], vec![1, 2]);
        assert!(meta.flags_with_missing_deps.is_empty());
        assert!(meta.transitive_deps[&2].is_empty());
    }

    #[test]
    fn test_compute_deps_self_cycle() {
        // Flag depends on itself
        let flags = vec![make_flag(
            1,
            "a",
            true,
            vec![group_with_properties(vec![flag_dep_property(1)])],
        )];
        let meta = compute_flag_dependencies(&flags).unwrap();

        assert!(meta.dependency_stages.is_empty());
        assert_eq!(meta.flags_with_missing_deps, vec![1]);
        assert!(meta.transitive_deps[&1].is_empty());
    }

    #[test]
    fn test_compute_deps_dependency_on_inactive_flag_not_missing() {
        // Active flag 2 depends on inactive flag 1 — but inactive flag 1's deps
        // are empty, so flag 2's edge to flag 1 is only based on its filter key.
        // Since flag 1 exists in the graph, flag 2 is NOT missing.
        let flags = vec![
            make_flag(1, "a", false, vec![group_with_properties(vec![])]),
            make_flag(
                2,
                "b",
                true,
                vec![group_with_properties(vec![flag_dep_property(1)])],
            ),
        ];
        let meta = compute_flag_dependencies(&flags).unwrap();

        assert_eq!(meta.dependency_stages.len(), 2);
        assert_eq!(meta.dependency_stages[0], vec![1]);
        assert_eq!(meta.dependency_stages[1], vec![2]);
        assert!(meta.flags_with_missing_deps.is_empty());
        assert_eq!(meta.transitive_deps[&2], HashSet::from([1]));
    }

    #[test]
    fn test_compute_deps_three_node_cycle_with_dependent() {
        // A→B→C→A form a cycle; D depends on A
        // All four should be flagged as missing
        let flags = vec![
            make_flag(
                1,
                "a",
                true,
                vec![group_with_properties(vec![flag_dep_property(2)])],
            ),
            make_flag(
                2,
                "b",
                true,
                vec![group_with_properties(vec![flag_dep_property(3)])],
            ),
            make_flag(
                3,
                "c",
                true,
                vec![group_with_properties(vec![flag_dep_property(1)])],
            ),
            make_flag(
                4,
                "d",
                true,
                vec![group_with_properties(vec![flag_dep_property(1)])],
            ),
        ];
        let meta = compute_flag_dependencies(&flags).unwrap();

        // Cycle participants and their dependents are all removed from the graph
        assert!(meta.dependency_stages.is_empty());
        assert_eq!(meta.flags_with_missing_deps, vec![1, 2, 3, 4]);
    }

    #[test]
    fn test_extract_deps_multiple_dependencies() {
        // Flag with 2 dependencies
        let flag = make_flag(
            3,
            "c",
            true,
            vec![group_with_properties(vec![
                flag_dep_property(1),
                flag_dep_property(2),
            ])],
        );
        let deps = extract_direct_flag_dependency_ids(&flag);
        assert_eq!(deps, HashSet::from([1, 2]));
    }

    #[test]
    fn test_compute_deps_transitive_deps_serialization_empty_set() {
        // Verify that a flag with no deps serializes as empty array
        let flags = vec![
            make_flag(1, "a", true, vec![group_with_properties(vec![])]),
            make_flag(
                2,
                "b",
                true,
                vec![group_with_properties(vec![flag_dep_property(1)])],
            ),
        ];
        let meta = compute_flag_dependencies(&flags).unwrap();
        let json = serde_json::to_value(&meta).unwrap();
        let td = json["transitive_deps"].as_object().unwrap();
        assert_eq!(td["1"], serde_json::json!([]));
        assert_eq!(td["2"], serde_json::json!([1]));
    }

    #[test]
    fn test_compute_deps_matches_golden_fixture() {
        let fixture = include_str!("../../tests/fixtures/hypercache_contract.json");
        let wrapper: HypercacheFlagsWrapper =
            serde_json::from_str(fixture).expect("fixture should deserialize");

        let computed = compute_flag_dependencies(&wrapper.flags).unwrap();

        assert_eq!(
            computed.dependency_stages,
            wrapper.evaluation_metadata.dependency_stages
        );
        assert_eq!(
            computed.flags_with_missing_deps,
            wrapper.evaluation_metadata.flags_with_missing_deps
        );
        assert_eq!(
            computed.transitive_deps,
            wrapper.evaluation_metadata.transitive_deps
        );
    }

    // -------------------------------------------------------------------------
    // retain_evaluable_and_referenced_flags tests
    // -------------------------------------------------------------------------

    #[test_case(true, false, true ; "active flag kept")]
    #[test_case(false, false, false ; "unreferenced inactive flag dropped")]
    #[test_case(true, true, false ; "deleted flag dropped")]
    fn test_retain_unreferenced_flag(active: bool, deleted: bool, expect_kept: bool) {
        let mut flags = vec![make_flag(
            1,
            "flag_a",
            active,
            vec![group_with_properties(vec![])],
        )];
        flags[0].deleted = deleted;

        retain_evaluable_and_referenced_flags(&mut flags);

        assert_eq!(flags.iter().any(|f| f.id == 1), expect_kept);
    }

    #[test]
    fn test_retain_keeps_deleted_flag_referenced_by_active_dependent() {
        // Mirrors Python's deleted_flag_referenced_by_active_dependent_kept case, so a
        // Rust-only edit that drops deleted flags before consulting references fails here
        // instead of splitting the two writers' flag sets.
        let mut flags = vec![
            make_flag(1, "dep", true, vec![group_with_properties(vec![])]),
            make_flag(
                2,
                "dependent",
                true,
                vec![group_with_properties(vec![flag_dep_property(1)])],
            ),
        ];
        flags[0].deleted = true;

        retain_evaluable_and_referenced_flags(&mut flags);

        let ids: Vec<i32> = flags.iter().map(|f| f.id).collect();
        assert_eq!(ids, vec![1, 2]);
    }

    #[test]
    fn test_retain_truncates_chains_at_the_first_unevaluable_hop() {
        // active 3 → inactive 2 → inactive 1: flag 2 stays (it pre-seeds as false
        // for flag 3's condition); flag 1 goes (flag 2's conditions are never read).
        let mut flags = vec![
            make_flag(1, "tail", false, vec![group_with_properties(vec![])]),
            make_flag(
                2,
                "middle",
                false,
                vec![group_with_properties(vec![flag_dep_property(1)])],
            ),
            make_flag(
                3,
                "head",
                true,
                vec![group_with_properties(vec![flag_dep_property(2)])],
            ),
        ];

        retain_evaluable_and_referenced_flags(&mut flags);

        let ids: Vec<i32> = flags.iter().map(|f| f.id).collect();
        assert_eq!(ids, vec![2, 3]);
    }

    // -------------------------------------------------------------------------
    // blank_inactive_filters tests
    // -------------------------------------------------------------------------

    #[test_case(true, false, false ; "active flag keeps its filters")]
    #[test_case(false, false, true ; "inactive flag is blanked")]
    #[test_case(true, true, true ; "deleted flag is blanked")]
    fn test_blank_inactive_filters(active: bool, deleted: bool, expect_blanked: bool) {
        let mut flags = vec![make_flag(
            1,
            "flag_a",
            active,
            vec![group_with_properties(vec![flag_dep_property(2)])],
        )];
        flags[0].deleted = deleted;
        // Populated beyond `groups` so clearing only `groups` is distinguishable from a
        // full reset. A partial clear would keep keys the Python writer's blank shape
        // never has, so the two writers' entries would disagree.
        flags[0].filters.payloads = Some(serde_json::json!({"true": "payload"}));
        flags[0].filters.early_exit = Some(true);
        let before = serde_json::to_value(&flags[0].filters).unwrap();

        blank_inactive_filters(&mut flags);

        let after = serde_json::to_value(&flags[0].filters).unwrap();
        if expect_blanked {
            // Python's `_blank_inactive_filters()` writes exactly this into the same
            // hypercache entry. If this fails, reconcile the literal in that function
            // (products/feature_flags/backend/flags_cache.py) with this shape.
            assert_eq!(after, serde_json::json!({"groups": []}));
        } else {
            assert_eq!(after, before);
        }
        // The entry has to survive so a dependency on it seeds as false in the matcher.
        assert_eq!(flags[0].id, 1);
    }

    #[tokio::test]
    async fn test_build_flags_cache_drops_unreferenced_and_blanks_referenced() {
        // Covers the wiring rather than the helpers: the two cache-writing binaries call
        // `build_flags_cache`, so an edit that stops it dropping or blanking would split
        // the payload from the Python writer while every helper test stayed green.
        let context = TestContext::new(None).await;
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team");

        let targeting = serde_json::json!({
            "groups": [{"properties": [], "rollout_percentage": 100}],
            "payloads": {"true": "payload"},
        });
        let disabled_row = |key: &str| FeatureFlagRow {
            key: key.to_string(),
            active: false,
            filters: targeting.clone(),
            ..base_flag_row(team.id)
        };
        let referenced = context
            .insert_flag(team.id, Some(disabled_row("referenced-disabled-flag")))
            .await
            .expect("Failed to insert referenced inactive flag");
        let unreferenced = context
            .insert_flag(team.id, Some(disabled_row("unreferenced-disabled-flag")))
            .await
            .expect("Failed to insert unreferenced inactive flag");
        let dependent = context
            .insert_flag(
                team.id,
                Some(FeatureFlagRow {
                    key: "active-flag".to_string(),
                    filters: serde_json::json!({
                        "groups": [{
                            "properties": [{
                                "key": referenced.id.to_string(),
                                "type": "flag",
                                "value": "false",
                                "operator": "flag_evaluates_to",
                            }],
                            "rollout_percentage": 100,
                        }],
                        "payloads": {"true": "payload"},
                    }),
                    ..base_flag_row(team.id)
                }),
            )
            .await
            .expect("Failed to insert dependent flag");

        let wrapper = build_flags_cache(context.non_persons_reader.clone(), team.id)
            .await
            .expect("Failed to build flags cache");

        let by_id: HashMap<i32, &FeatureFlag> = wrapper.flags.iter().map(|f| (f.id, f)).collect();
        assert_eq!(
            by_id.keys().copied().collect::<HashSet<_>>(),
            HashSet::from([referenced.id, dependent.id])
        );
        assert_eq!(
            serde_json::to_value(&by_id[&referenced.id].filters).unwrap(),
            serde_json::json!({"groups": []})
        );
        // Asserted field-wise rather than against the inserted JSON, because a JSONB round
        // trip through `Option<f64>` renders `rollout_percentage` as 100.0 and serde_json
        // holds integer and float numbers unequal.
        let dependent_filters = &by_id[&dependent.id].filters;
        assert_eq!(dependent_filters.groups.len(), 1);
        assert_eq!(
            dependent_filters.payloads,
            Some(serde_json::json!({"true": "payload"}))
        );

        // Metadata is computed on the post-drop set.
        let meta = &wrapper.evaluation_metadata;
        let staged_ids: HashSet<i32> = meta.dependency_stages.iter().flatten().copied().collect();
        assert_eq!(staged_ids, HashSet::from([referenced.id, dependent.id]));
        assert!(!meta.transitive_deps.contains_key(&unreferenced.id));
        assert_eq!(
            meta.transitive_deps[&dependent.id],
            HashSet::from([referenced.id])
        );
        assert!(meta.flags_with_missing_deps.is_empty());
    }
}
