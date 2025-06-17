use std::collections::{HashMap, HashSet, VecDeque};

use petgraph::{algo::toposort, graph::DiGraph};

use crate::api::errors::FlagError;

/// Trait for types that can provide their dependencies
pub trait DependencyProvider {
    type Id: Copy + Eq + std::hash::Hash + std::fmt::Display + Into<i64>;
    type Error;

    /// Get the ID of this item
    fn get_id(&self) -> Self::Id;

    /// Extract dependencies for this item
    fn extract_dependencies(&self) -> Result<HashSet<Self::Id>, Self::Error>;

    /// Get the dependency type for this provider
    fn dependency_type() -> DependencyType;
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DependencyType {
    Flag,
    Cohort,
}

impl std::fmt::Display for DependencyType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        // Rely on the default implementation of the Debug trait and then lower case it.
        f.write_str(&format!("{:?}", self).to_lowercase())
    }
}

/// Constructs a dependency graph for any type that implements DependencyProvider.
/// This graph represents dependencies between entities (e.g. feature flags or cohorts).
///
/// Graph semantics:
/// - Each node represents a flag or cohort.
/// - Edges point from dependent to dependency:
///     A → B  means "A depends on B"
///     Note: Topological sorts expect edges to point from dependency to
///     dependent (not dependent to dependency as we do here). This is why
///     we reverse the output of the topological sort later.
/// - This is a Directed Acyclic Graph (DAG); cycles are not allowed.
///
/// Example dependency graph:
/// ```text
///   A  B
///   ↓ ↘ ↓
///   C   D
///    ↘ ↙
///     E
/// ```
/// In this example:
/// - A and B are root nodes (no dependencies).
/// - C depends on A and B.
/// - D depends on B.
/// - E depends on C and D.
///
/// Evaluation order:
/// - Because we model edges as "dependent → dependency", we reverse the output of the topological sort
///   to obtain the correct evaluation order.
/// - After reversing, dependencies are guaranteed to be evaluated before dependents.
///
/// DAG invariants:
/// - All dependencies must be evaluated before evaluating dependents.
/// - Cycles indicate invalid configuration and must be rejected.
pub fn build_dependency_graph<T, E, F>(
    initial_id: T::Id,
    items: &[T],
    criteria: F, // The first item must meet the criteria for us to continue.
) -> Result<DiGraph<T::Id, ()>, E>
where
    T: DependencyProvider<Error = E>,
    E: From<FlagError>,
    F: Fn(&T) -> bool,
{
    let mut graph = DiGraph::new();
    let mut node_map = HashMap::new();
    let mut queue = VecDeque::new();

    // Find the initial item
    let initial_item = items
        .iter()
        .find(|item| item.get_id() == initial_id)
        .ok_or_else(|| FlagError::DependencyNotFound(T::dependency_type(), initial_id.into()))?;

    // Check if the initial item meets the criteria
    if !criteria(initial_item) {
        return Ok(graph);
    }

    // This implements a breadth-first search (BFS) traversal to build a directed graph of item dependencies.
    // Starting from the initial item, we:
    // 1. Add each item as a node in the graph
    // 2. Track visited nodes in a map to avoid duplicates
    // 3. For each item, get its dependencies and add directed edges from the item to its dependencies
    // 4. Queue up any unvisited dependencies to process their dependencies later
    // This builds up the full dependency graph level by level, which we can later check for cycles
    queue.push_back(initial_id);
    node_map.insert(initial_id, graph.add_node(initial_id));

    while let Some(item_id) = queue.pop_front() {
        let item = items
            .iter()
            .find(|item| item.get_id() == item_id)
            .ok_or_else(|| FlagError::DependencyNotFound(T::dependency_type(), item_id.into()))?;

        let dependencies = item.extract_dependencies()?;
        for dep_id in dependencies {
            // Retrieve the current node **before** mutable borrowing
            // This is safe because we're not mutating the node map,
            // and it keeps the borrow checker happy
            let current_node = node_map[&item_id];

            // Add dependency node if we haven't seen this dependency ID before in our traversal.
            // This happens when we discover a new dependency that wasn't previously
            // encountered while processing other dependencies in the graph.
            let is_new_dep = !node_map.contains_key(&dep_id);
            let dep_node = node_map
                .entry(dep_id)
                .or_insert_with(|| graph.add_node(dep_id));
            graph.add_edge(current_node, *dep_node, ());
            if is_new_dep {
                queue.push_back(dep_id);
            }
        }
    }

    // Use toposort to detect cycles and get the cycle starting point
    match toposort(&graph, None) {
        Ok(_) => Ok(graph),
        Err(e) => {
            // Use the node that started the cycle (from the toposort error)
            let cycle_start_id = e.node_id();
            let dependency_id = graph[cycle_start_id].into();
            Err(FlagError::DependencyCycle(T::dependency_type(), dependency_id).into())
        }
    }
}
