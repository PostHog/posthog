use std::collections::{BTreeMap, VecDeque};
use std::fmt;
use std::mem::size_of;

use rand::rngs::StdRng;
use rand::{Rng, SeedableRng};
use serde::Serialize;
use serde_json::Value;
use uuid::Uuid;

use super::ops::{
    CanonicalReadPayload, DistinctIdAssignmentPayload, DistinctIdMove, FullMergePayload,
    MergeShape, NanosSincePhaseStart, OpDescriptor, OpPayload, OperationId, PersonUpsertPayload,
    ReadExpectation,
};

const ZIPF_EXPONENT: f64 = 1.5;
const RECENT_SELECTION_ATTEMPTS: usize = 8;
const FANOUT_ROLLS: u32 = 100_000;
const WHALE_MIN_FANOUT: u32 = 101;
const PROPERTY_SEED_MIX: u64 = 0xa076_1d64_78bd_642f;
const NONE_INDEX: u32 = u32::MAX;
const PENDING_INDEX: u32 = u32::MAX - 1;
const ARENA_CHUNK_CAPACITY: usize = 65_536;

// RFC sample: 95% single-DID, almost all remaining at 2, with rare large tails.
const FANOUT_BUCKETS: [FanoutBucket; 4] = [
    FanoutBucket::new(95_000, 1, 1),
    FanoutBucket::new(99_990, 2, 2),
    FanoutBucket::new(99_999, 3, 100),
    FanoutBucket::new(FANOUT_ROLLS, 101, 1_000),
];

#[derive(Debug, Clone, Copy)]
struct FanoutBucket {
    upper_roll_exclusive: u32,
    min: u32,
    max: u32,
}

impl FanoutBucket {
    const fn new(upper_roll_exclusive: u32, min: u32, max: u32) -> Self {
        Self {
            upper_roll_exclusive,
            min,
            max,
        }
    }
}

#[derive(Debug, Clone)]
pub struct WorldConfig {
    pub seed: u64,
    pub team_count: i32,
    pub initial_person_count: usize,
    pub recent_capacity_per_team: usize,
    pub recent_target_percent: u8,
    pub property_bytes: usize,
}

impl Default for WorldConfig {
    fn default() -> Self {
        Self {
            seed: 42,
            team_count: 100,
            initial_person_count: 100_000,
            recent_capacity_per_team: 4_096,
            recent_target_percent: 50,
            property_bytes: 700,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ReplayMode {
    Fresh,
    Stale,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AssignmentMode {
    New,
    FreshExisting,
    StaleReplay,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ReadMode {
    Hit,
    Miss,
}

#[derive(Debug, Clone, PartialEq)]
pub struct CreationDescriptors {
    pub person_upsert: OpDescriptor,
    pub distinct_id_assignment: OpDescriptor,
    pub activation: PendingCreationToken,
}

#[derive(Debug, Clone, PartialEq)]
pub struct AssignmentDescriptor {
    pub operation: OpDescriptor,
    pub activation: Option<PendingDistinctIdToken>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PendingCreationToken {
    person: PersonKey,
    distinct_id: DistinctIdKey,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PendingDistinctIdToken {
    distinct_id: DistinctIdKey,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
#[repr(transparent)]
struct PersonKey(u32);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(transparent)]
struct DistinctIdKey(u32);

#[derive(Debug)]
struct ChunkedArena<T> {
    chunks: Vec<Vec<T>>,
    len: u32,
}

impl<T> ChunkedArena<T> {
    fn new() -> Self {
        Self {
            chunks: Vec::new(),
            len: 0,
        }
    }

    fn push(&mut self, value: T) -> Option<u32> {
        if self.len >= PENDING_INDEX {
            return None;
        }
        if self
            .chunks
            .last()
            .is_none_or(|chunk| chunk.len() == ARENA_CHUNK_CAPACITY)
        {
            self.chunks.push(Vec::with_capacity(ARENA_CHUNK_CAPACITY));
        }
        let index = self.len;
        self.chunks.last_mut()?.push(value);
        self.len += 1;
        Some(index)
    }

    fn can_push(&self, count: u32) -> bool {
        self.len
            .checked_add(count)
            .is_some_and(|len| len <= PENDING_INDEX)
    }

    fn len(&self) -> usize {
        self.len as usize
    }

    fn get(&self, index: u32) -> &T {
        let index = index as usize;
        &self.chunks[index / ARENA_CHUNK_CAPACITY][index % ARENA_CHUNK_CAPACITY]
    }

    fn get_mut(&mut self, index: u32) -> &mut T {
        let index = index as usize;
        &mut self.chunks[index / ARENA_CHUNK_CAPACITY][index % ARENA_CHUNK_CAPACITY]
    }

    fn iter(&self) -> impl Iterator<Item = &T> {
        self.chunks.iter().flat_map(|chunk| chunk.iter())
    }

    #[cfg(test)]
    fn chunk_count(&self) -> usize {
        self.chunks.len()
    }
}

#[derive(Debug)]
#[repr(C)]
struct PersonState {
    version: i64,
    first_distinct_id: u32,
    last_distinct_id: u32,
    distinct_id_count: u32,
    team_index: u32,
    live_index: u32,
    whale_index: u32,
}

impl PersonState {
    fn new(team_index: u32, live_index: u32) -> Self {
        Self {
            version: 1,
            first_distinct_id: NONE_INDEX,
            last_distinct_id: NONE_INDEX,
            distinct_id_count: 0,
            team_index,
            live_index,
            whale_index: NONE_INDEX,
        }
    }

    fn first_distinct_id(&self) -> Option<DistinctIdKey> {
        (self.first_distinct_id != NONE_INDEX).then_some(DistinctIdKey(self.first_distinct_id))
    }

    fn last_distinct_id(&self) -> Option<DistinctIdKey> {
        (self.last_distinct_id != NONE_INDEX).then_some(DistinctIdKey(self.last_distinct_id))
    }

    fn live_index(&self) -> Option<usize> {
        (self.live_index != NONE_INDEX).then_some(self.live_index as usize)
    }

    fn whale_index(&self) -> Option<usize> {
        (self.whale_index != NONE_INDEX).then_some(self.whale_index as usize)
    }

    fn clear_distinct_ids(&mut self) {
        self.first_distinct_id = NONE_INDEX;
        self.last_distinct_id = NONE_INDEX;
        self.distinct_id_count = 0;
    }
}

#[derive(Debug)]
#[repr(C)]
struct DistinctIdState {
    version: i64,
    owner: PersonKey,
    next: u32,
}

impl DistinctIdState {
    fn next(&self) -> Option<DistinctIdKey> {
        (self.next < PENDING_INDEX).then_some(DistinctIdKey(self.next))
    }

    fn is_pending(&self) -> bool {
        self.next == PENDING_INDEX
    }
}

#[derive(Debug)]
struct TeamState {
    team_id: i32,
    live_persons: Vec<PersonKey>,
    whales: Vec<PersonKey>,
    recent: VecDeque<PersonKey>,
    pending_persons: u32,
}

impl TeamState {
    fn new(team_id: i32, initial_person_count: usize) -> Self {
        Self {
            team_id,
            live_persons: Vec::with_capacity(initial_person_count),
            whales: Vec::new(),
            recent: VecDeque::new(),
            pending_persons: 0,
        }
    }
}

#[derive(Debug)]
pub struct WorldState {
    topology_rng: StdRng,
    property_rng: StdRng,
    seed: u64,
    property_bytes: usize,
    recent_capacity_per_team: usize,
    recent_target_percent: u8,
    team_cdf: Vec<f64>,
    teams: Vec<TeamState>,
    persons: ChunkedArena<PersonState>,
    distinct_ids: ChunkedArena<DistinctIdState>,
    pending_distinct_ids_by_person: BTreeMap<PersonKey, u32>,
    growth_reservation_enabled: bool,
    next_miss_counter: u64,
    next_operation_id: u64,
}

impl WorldState {
    pub fn new(config: WorldConfig) -> Result<Self, WorldError> {
        if config.team_count <= 0 {
            return Err(WorldError::InvalidTeamCount(config.team_count));
        }
        if config.recent_target_percent > 100 {
            return Err(WorldError::InvalidRecentTargetPercent(
                config.recent_target_percent,
            ));
        }
        if u64::try_from(config.initial_person_count).unwrap_or(u64::MAX) >= u64::from(u32::MAX) {
            return Err(WorldError::PopulationTooLarge(config.initial_person_count));
        }

        let weights: Vec<f64> = (1..=config.team_count)
            .map(|rank| 1.0 / f64::from(rank).powf(ZIPF_EXPONENT))
            .collect();
        let team_counts = allocate_zipf_counts(&weights, config.initial_person_count);
        let total_weight: f64 = weights.iter().sum();
        let mut cumulative = 0.0;
        let team_cdf = weights
            .iter()
            .map(|weight| {
                cumulative += weight / total_weight;
                cumulative
            })
            .collect::<Vec<_>>();

        let teams = team_counts
            .iter()
            .enumerate()
            .map(|(team_index, count)| TeamState::new(team_index as i32 + 1, *count))
            .collect();
        let mut world = Self {
            topology_rng: StdRng::seed_from_u64(config.seed),
            property_rng: StdRng::seed_from_u64(config.seed ^ PROPERTY_SEED_MIX),
            seed: config.seed,
            property_bytes: config.property_bytes,
            recent_capacity_per_team: config.recent_capacity_per_team,
            recent_target_percent: config.recent_target_percent,
            team_cdf,
            teams,
            persons: ChunkedArena::new(),
            distinct_ids: ChunkedArena::new(),
            pending_distinct_ids_by_person: BTreeMap::new(),
            growth_reservation_enabled: false,
            next_miss_counter: 1,
            next_operation_id: 1,
        };

        for (team_index, count) in team_counts.into_iter().enumerate() {
            for _ in 0..count {
                let fanout = world.sample_fanout();
                world.create_person(team_index, fanout)?;
            }
        }
        Ok(world)
    }

    pub fn population(&self) -> PopulationView<'_> {
        PopulationView { world: self }
    }

    pub fn live_person_count(&self) -> usize {
        self.teams.iter().map(|team| team.live_persons.len()).sum()
    }

    pub fn distinct_id_count(&self) -> usize {
        self.distinct_ids.len()
    }

    pub fn reserve_person_growth(
        &mut self,
        person_creations: PersonCreationCount,
    ) -> Result<(), WorldError> {
        let total = usize::try_from(person_creations.get())
            .map_err(|_| WorldError::MemoryEstimateOverflow)?;
        let mut previous = 0.0;
        let weights = self
            .team_cdf
            .iter()
            .map(|cumulative| {
                let weight = cumulative - previous;
                previous = *cumulative;
                weight
            })
            .collect::<Vec<_>>();
        for (team, additional) in self
            .teams
            .iter_mut()
            .zip(allocate_zipf_counts(&weights, total))
        {
            team.live_persons
                .try_reserve_exact(additional)
                .map_err(|_| WorldError::AllocationFailed("team live person"))?;
        }
        self.growth_reservation_enabled = true;
        Ok(())
    }

    pub fn estimate_initial_memory(
        config: &WorldConfig,
    ) -> Result<WorldMemoryEstimate, WorldError> {
        Self::estimate_memory(config, WorldGrowth::default())
    }

    pub fn estimate_memory(
        config: &WorldConfig,
        growth: WorldGrowth,
    ) -> Result<WorldMemoryEstimate, WorldError> {
        if config.team_count <= 0 {
            return Err(WorldError::InvalidTeamCount(config.team_count));
        }
        let initial_person_count = u64::try_from(config.initial_person_count)
            .map_err(|_| WorldError::MemoryEstimateOverflow)?;
        let person_count = initial_person_count
            .checked_add(growth.person_creations.get())
            .ok_or(WorldError::MemoryEstimateOverflow)?;
        let distinct_id_count = expected_distinct_id_count(initial_person_count)?
            .checked_add(growth.person_creations.get())
            .and_then(|count| count.checked_add(growth.distinct_id_assignments.get()))
            .ok_or(WorldError::MemoryEstimateOverflow)?;
        let person_chunks = chunk_count(person_count)?;
        let distinct_id_chunks = chunk_count(distinct_id_count)?;
        let person_arena_bytes = chunk_allocation_bytes(person_chunks, size_of::<PersonState>())?;
        let distinct_id_arena_bytes =
            chunk_allocation_bytes(distinct_id_chunks, size_of::<DistinctIdState>())?;
        let live_person_index_bytes = checked_product(person_count, size_of::<PersonKey>() as u64)?;
        let recent_capacity = checked_product(
            config.team_count as u64,
            config.recent_capacity_per_team as u64,
        )?;
        let recent_index_bytes = checked_product(recent_capacity, size_of::<PersonKey>() as u64)?;
        let initial_whale_count = div_ceil(
            checked_product(initial_person_count, whale_bucket_rolls())?,
            u64::from(FANOUT_ROLLS),
        )?;
        let whale_count = initial_whale_count
            .checked_add(growth.distinct_id_assignments.get().min(person_count))
            .ok_or(WorldError::MemoryEstimateOverflow)?
            .min(person_count);
        let whale_index_bytes = checked_product(whale_count, size_of::<PersonKey>() as u64)?;
        let team_state_bytes =
            checked_product(config.team_count as u64, size_of::<TeamState>() as u64)?;
        let chunk_metadata_bytes = checked_product(
            person_chunks
                .checked_add(distinct_id_chunks)
                .ok_or(WorldError::MemoryEstimateOverflow)?,
            size_of::<Vec<PersonState>>() as u64,
        )?;
        let total_bytes = [
            person_arena_bytes,
            distinct_id_arena_bytes,
            live_person_index_bytes,
            recent_index_bytes,
            whale_index_bytes,
            team_state_bytes,
            chunk_metadata_bytes,
        ]
        .into_iter()
        .try_fold(0u64, |total, bytes| {
            total
                .checked_add(bytes)
                .ok_or(WorldError::MemoryEstimateOverflow)
        })?;

        Ok(WorldMemoryEstimate {
            growth,
            person_count,
            expected_distinct_id_count: distinct_id_count,
            person_slot_bytes: size_of::<PersonState>(),
            distinct_id_slot_bytes: size_of::<DistinctIdState>(),
            person_arena_bytes,
            distinct_id_arena_bytes,
            live_person_index_bytes,
            recent_index_bytes,
            whale_index_bytes,
            chunk_metadata_bytes,
            total_bytes,
        })
    }

    pub fn resolve_person_upsert(
        &mut self,
        scheduled_at: NanosSincePhaseStart,
        replay: ReplayMode,
    ) -> Result<OpDescriptor, WorldError> {
        let team_index = self.select_team(|team| !team.live_persons.is_empty())?;
        let person_key = self.select_person(team_index, None, false, false)?;
        let current_version = self.person(person_key).version;
        let version = match replay {
            ReplayMode::Fresh => {
                let version = increment_version(current_version)?;
                self.person_mut(person_key).version = version;
                version
            }
            ReplayMode::Stale => stale_version(current_version),
        };
        let payload = PersonUpsertPayload {
            team_id: self.teams[team_index].team_id,
            person_uuid: self.person_uuid(person_key),
            properties: generate_properties(&mut self.property_rng, self.property_bytes),
            version,
        };
        self.touch_person(person_key);
        self.describe(scheduled_at, OpPayload::PersonUpsert(payload))
    }

    pub fn resolve_distinct_id_assignment(
        &mut self,
        scheduled_at: NanosSincePhaseStart,
        mode: AssignmentMode,
    ) -> Result<AssignmentDescriptor, WorldError> {
        let team_index = self.select_team(|team| !team.live_persons.is_empty())?;
        let person_key = self.select_person(team_index, None, false, false)?;
        let distinct_id_key = match mode {
            AssignmentMode::New => self.reserve_distinct_id(person_key)?,
            AssignmentMode::FreshExisting | AssignmentMode::StaleReplay => {
                self.select_distinct_id(person_key)?
            }
        };
        let version = match mode {
            AssignmentMode::New => self.distinct_id(distinct_id_key).version,
            AssignmentMode::FreshExisting => {
                let version = increment_version(self.distinct_id(distinct_id_key).version)?;
                self.distinct_id_mut(distinct_id_key).version = version;
                version
            }
            AssignmentMode::StaleReplay => stale_version(self.distinct_id(distinct_id_key).version),
        };
        let payload = DistinctIdAssignmentPayload {
            team_id: self.teams[team_index].team_id,
            person_uuid: self.person_uuid(person_key),
            distinct_id: self.distinct_id_value(distinct_id_key),
            version,
        };
        self.touch_person(person_key);
        let operation = self.describe(scheduled_at, OpPayload::DistinctIdAssignment(payload))?;
        Ok(AssignmentDescriptor {
            operation,
            activation: (mode == AssignmentMode::New).then_some(PendingDistinctIdToken {
                distinct_id: distinct_id_key,
            }),
        })
    }

    pub fn resolve_creation(
        &mut self,
        scheduled_at: NanosSincePhaseStart,
    ) -> Result<CreationDescriptors, WorldError> {
        let enforce_reservation = self.growth_reservation_enabled;
        let team_index = self.select_team(|team| {
            !enforce_reservation
                || team
                    .live_persons
                    .len()
                    .saturating_add(team.pending_persons as usize)
                    < team.live_persons.capacity()
        })?;
        let person_key = self.reserve_person(team_index)?;
        let distinct_id_key = self.reserve_distinct_id(person_key)?;
        let team_id = self.teams[team_index].team_id;
        let person_uuid = self.person_uuid(person_key);
        let person_version = self.person(person_key).version;
        let distinct_id_value = self.distinct_id_value(distinct_id_key);
        let distinct_id_version = self.distinct_id(distinct_id_key).version;
        let properties = generate_properties(&mut self.property_rng, self.property_bytes);

        let person_upsert = self.describe(
            scheduled_at,
            OpPayload::PersonUpsert(PersonUpsertPayload {
                team_id,
                person_uuid,
                properties,
                version: person_version,
            }),
        )?;
        let distinct_id_assignment = self.describe(
            scheduled_at,
            OpPayload::DistinctIdAssignment(DistinctIdAssignmentPayload {
                team_id,
                person_uuid,
                distinct_id: distinct_id_value,
                version: distinct_id_version,
            }),
        )?;
        Ok(CreationDescriptors {
            person_upsert,
            distinct_id_assignment,
            activation: PendingCreationToken {
                person: person_key,
                distinct_id: distinct_id_key,
            },
        })
    }

    pub fn activate_creation(&mut self, token: PendingCreationToken) -> Result<(), WorldError> {
        if self.person(token.person).live_index().is_some()
            || !self.distinct_id(token.distinct_id).is_pending()
            || self.distinct_id(token.distinct_id).owner != token.person
        {
            return Err(WorldError::InvalidPendingActivation);
        }
        self.activate_person(token.person)?;
        self.activate_distinct_id_key(token.distinct_id)?;
        self.touch_person(token.person);
        Ok(())
    }

    pub fn activate_distinct_id(
        &mut self,
        token: PendingDistinctIdToken,
    ) -> Result<(), WorldError> {
        self.activate_distinct_id_key(token.distinct_id)
    }

    pub fn abandon_distinct_id(&mut self, token: PendingDistinctIdToken) -> Result<(), WorldError> {
        if !self.distinct_id(token.distinct_id).is_pending() {
            return Err(WorldError::InvalidPendingActivation);
        }
        let person_key = self.distinct_id(token.distinct_id).owner;
        self.remove_pending_distinct_id(person_key)
    }

    pub fn resolve_full_merge(
        &mut self,
        scheduled_at: NanosSincePhaseStart,
    ) -> Result<OpDescriptor, WorldError> {
        self.resolve_merge(scheduled_at, MergeShape::Standard)
    }

    pub fn resolve_whale_merge(
        &mut self,
        scheduled_at: NanosSincePhaseStart,
    ) -> Result<OpDescriptor, WorldError> {
        self.resolve_merge(scheduled_at, MergeShape::Whale)
    }

    pub fn resolve_read(
        &mut self,
        scheduled_at: NanosSincePhaseStart,
        mode: ReadMode,
    ) -> Result<OpDescriptor, WorldError> {
        let team_index = self.select_team(|team| !team.live_persons.is_empty())?;
        let team_id = self.teams[team_index].team_id;
        let payload = match mode {
            ReadMode::Hit => {
                let person_key = self.select_person(team_index, None, false, false)?;
                let distinct_id_key = self.select_distinct_id(person_key)?;
                let payload = CanonicalReadPayload {
                    team_id,
                    distinct_id: self.distinct_id_value(distinct_id_key),
                    expectation: ReadExpectation::Hit,
                };
                self.touch_person(person_key);
                payload
            }
            ReadMode::Miss => CanonicalReadPayload {
                team_id,
                distinct_id: self.next_miss_distinct_id()?,
                expectation: ReadExpectation::Miss,
            },
        };
        self.describe(scheduled_at, OpPayload::CanonicalRead(payload))
    }

    fn resolve_merge(
        &mut self,
        scheduled_at: NanosSincePhaseStart,
        shape: MergeShape,
    ) -> Result<OpDescriptor, WorldError> {
        let eligible_teams = self
            .teams
            .iter()
            .map(|team| {
                let sources = if shape == MergeShape::Whale {
                    &team.whales
                } else {
                    &team.live_persons
                };
                team.live_persons.len() >= 2
                    && sources
                        .iter()
                        .any(|source| !self.pending_distinct_ids_by_person.contains_key(source))
            })
            .collect::<Vec<_>>();
        let team_index = self.select_eligible_team(&eligible_teams)?;
        let source = self.select_person(team_index, None, shape == MergeShape::Whale, true)?;
        let target = self.select_person(team_index, Some(source), false, false)?;

        let source_version = self.person(source).version;
        let target_version = self.person(target).version;
        let merged_target_version = source_version
            .max(target_version)
            .checked_add(1)
            .ok_or(WorldError::VersionExhausted)?;
        let source_tombstone_version = source_version
            .checked_add(100)
            .ok_or(WorldError::VersionExhausted)?;
        let source_first = self.person(source).first_distinct_id();
        let source_last = self.person(source).last_distinct_id();
        let source_count = self.person(source).distinct_id_count;
        let target_first = self.person(target).first_distinct_id();
        let target_last = self.person(target).last_distinct_id();
        let merged_count = self
            .person(target)
            .distinct_id_count
            .checked_add(source_count)
            .ok_or(WorldError::FanoutExhausted)?;

        let mut planned_moves = Vec::with_capacity(source_count as usize);
        let mut current = source_first;
        while let Some(distinct_id_key) = current {
            let distinct_id = self.distinct_id(distinct_id_key);
            let version = increment_version(distinct_id.version)?;
            planned_moves.push((
                distinct_id_key,
                version,
                self.distinct_id_value(distinct_id_key),
            ));
            current = distinct_id.next();
        }

        if let (Some(target_last), Some(source_first)) = (target_last, source_first) {
            self.distinct_id_mut(target_last).next = source_first.0;
        }
        let mut moves = Vec::with_capacity(planned_moves.len());
        for (distinct_id_key, version, distinct_id) in planned_moves {
            let state = self.distinct_id_mut(distinct_id_key);
            state.owner = target;
            state.version = version;
            moves.push(DistinctIdMove {
                distinct_id,
                version,
            });
        }

        {
            let target_state = self.person_mut(target);
            target_state.first_distinct_id = target_first
                .or(source_first)
                .map_or(NONE_INDEX, |key| key.0);
            target_state.last_distinct_id =
                source_last.or(target_last).map_or(NONE_INDEX, |key| key.0);
            target_state.distinct_id_count = merged_count;
            target_state.version = merged_target_version;
        }
        {
            let source_state = self.person_mut(source);
            source_state.clear_distinct_ids();
            source_state.version = source_tombstone_version;
        }

        let source_uuid = self.person_uuid(source);
        let target_uuid = self.person_uuid(target);
        self.ensure_whale(target);
        self.remove_live_person(source);
        self.touch_person(target);

        let payload = FullMergePayload {
            team_id: self.teams[team_index].team_id,
            source_person_uuid: source_uuid,
            target_person_uuid: target_uuid,
            distinct_id_moves: moves.into_boxed_slice(),
            target_properties: generate_properties(&mut self.property_rng, self.property_bytes),
            target_version: merged_target_version,
            source_tombstone_version,
            shape,
        };
        self.describe(scheduled_at, OpPayload::FullMerge(payload))
    }

    fn describe(
        &mut self,
        scheduled_at: NanosSincePhaseStart,
        payload: OpPayload,
    ) -> Result<OpDescriptor, WorldError> {
        let operation_id = OperationId(self.next_operation_id);
        self.next_operation_id = self
            .next_operation_id
            .checked_add(1)
            .ok_or(WorldError::IdentifierExhausted("operation"))?;
        Ok(OpDescriptor::new(operation_id, scheduled_at, payload))
    }

    fn create_person(&mut self, team_index: usize, fanout: u32) -> Result<PersonKey, WorldError> {
        if !self.distinct_ids.can_push(fanout) {
            return Err(WorldError::ArenaExhausted("distinct ID"));
        }
        let person_key = self.reserve_person(team_index)?;
        self.activate_person(person_key)?;
        for _ in 0..fanout {
            self.create_distinct_id(person_key)?;
        }
        self.ensure_whale(person_key);
        self.touch_person(person_key);
        Ok(person_key)
    }

    fn reserve_person(&mut self, team_index: usize) -> Result<PersonKey, WorldError> {
        let pending_persons = self.teams[team_index]
            .pending_persons
            .checked_add(1)
            .ok_or(WorldError::IndexExhausted("pending person"))?;
        let team_index =
            u32::try_from(team_index).map_err(|_| WorldError::IndexExhausted("team"))?;
        let person_index = self
            .persons
            .push(PersonState::new(team_index, NONE_INDEX))
            .ok_or(WorldError::ArenaExhausted("person"))?;
        self.teams[team_index as usize].pending_persons = pending_persons;
        Ok(PersonKey(person_index))
    }

    fn activate_person(&mut self, person_key: PersonKey) -> Result<(), WorldError> {
        if self.person(person_key).live_index().is_some() {
            return Err(WorldError::InvalidPendingActivation);
        }
        let team_index = self.person(person_key).team_index as usize;
        let live_index = u32::try_from(self.teams[team_index].live_persons.len())
            .map_err(|_| WorldError::IndexExhausted("team live person"))?;
        self.teams[team_index].pending_persons = self.teams[team_index]
            .pending_persons
            .checked_sub(1)
            .ok_or(WorldError::InvalidPendingActivation)?;
        self.teams[team_index].live_persons.push(person_key);
        self.person_mut(person_key).live_index = live_index;
        Ok(())
    }

    fn create_distinct_id(&mut self, person_key: PersonKey) -> Result<DistinctIdKey, WorldError> {
        let distinct_id_key = self.reserve_distinct_id(person_key)?;
        self.activate_distinct_id_key(distinct_id_key)?;
        Ok(distinct_id_key)
    }

    fn reserve_distinct_id(&mut self, person_key: PersonKey) -> Result<DistinctIdKey, WorldError> {
        let distinct_id_index = self
            .distinct_ids
            .push(DistinctIdState {
                version: 1,
                owner: person_key,
                next: PENDING_INDEX,
            })
            .ok_or(WorldError::ArenaExhausted("distinct ID"))?;
        let pending = self
            .pending_distinct_ids_by_person
            .entry(person_key)
            .or_default();
        *pending = pending.checked_add(1).ok_or(WorldError::FanoutExhausted)?;
        Ok(DistinctIdKey(distinct_id_index))
    }

    fn activate_distinct_id_key(
        &mut self,
        distinct_id_key: DistinctIdKey,
    ) -> Result<(), WorldError> {
        if !self.distinct_id(distinct_id_key).is_pending() {
            return Err(WorldError::InvalidPendingActivation);
        }
        let person_key = self.distinct_id(distinct_id_key).owner;
        if self.person(person_key).live_index().is_none() {
            return Err(WorldError::InvalidPendingActivation);
        }
        let count = self
            .person(person_key)
            .distinct_id_count
            .checked_add(1)
            .ok_or(WorldError::FanoutExhausted)?;
        self.remove_pending_distinct_id(person_key)?;
        let previous_last = self.person(person_key).last_distinct_id();
        self.distinct_id_mut(distinct_id_key).next = NONE_INDEX;
        if let Some(previous_last) = previous_last {
            self.distinct_id_mut(previous_last).next = distinct_id_key.0;
        }
        let person = self.person_mut(person_key);
        if person.first_distinct_id == NONE_INDEX {
            person.first_distinct_id = distinct_id_key.0;
        }
        person.last_distinct_id = distinct_id_key.0;
        person.distinct_id_count = count;
        self.ensure_whale(person_key);
        Ok(())
    }

    fn remove_pending_distinct_id(&mut self, person_key: PersonKey) -> Result<(), WorldError> {
        let remove_entry = {
            let pending = self
                .pending_distinct_ids_by_person
                .get_mut(&person_key)
                .ok_or(WorldError::InvalidPendingActivation)?;
            *pending = pending
                .checked_sub(1)
                .ok_or(WorldError::InvalidPendingActivation)?;
            *pending == 0
        };
        if remove_entry {
            self.pending_distinct_ids_by_person.remove(&person_key);
        }
        Ok(())
    }

    fn person(&self, key: PersonKey) -> &PersonState {
        self.persons.get(key.0)
    }

    fn person_mut(&mut self, key: PersonKey) -> &mut PersonState {
        self.persons.get_mut(key.0)
    }

    fn distinct_id(&self, key: DistinctIdKey) -> &DistinctIdState {
        self.distinct_ids.get(key.0)
    }

    fn distinct_id_mut(&mut self, key: DistinctIdKey) -> &mut DistinctIdState {
        self.distinct_ids.get_mut(key.0)
    }

    fn person_uuid(&self, person_key: PersonKey) -> Uuid {
        Uuid::from_u128((u128::from(self.seed) << 64) | u128::from(person_key.0).saturating_add(1))
    }

    fn distinct_id_value(&self, distinct_id_key: DistinctIdKey) -> Box<str> {
        format!(
            "bench-{:016x}-{:016x}",
            self.seed,
            u64::from(distinct_id_key.0) + 1
        )
        .into_boxed_str()
    }

    fn next_miss_distinct_id(&mut self) -> Result<Box<str>, WorldError> {
        let counter = self.next_miss_counter;
        self.next_miss_counter = counter
            .checked_add(1)
            .ok_or(WorldError::IdentifierExhausted("read miss"))?;
        Ok(format!("bench-miss-{:016x}-{counter:016x}", self.seed).into_boxed_str())
    }

    fn sample_fanout(&mut self) -> u32 {
        let bucket_roll = self.topology_rng.gen_range(0..FANOUT_ROLLS);
        let within_bucket_roll = self.topology_rng.gen::<u64>();
        fanout_for_roll(bucket_roll, within_bucket_roll)
    }

    fn select_team<F>(&mut self, eligible: F) -> Result<usize, WorldError>
    where
        F: Fn(&TeamState) -> bool,
    {
        let eligible = self.teams.iter().map(eligible).collect::<Vec<_>>();
        self.select_eligible_team(&eligible)
    }

    fn select_eligible_team(&mut self, eligible: &[bool]) -> Result<usize, WorldError> {
        for _ in 0..self.teams.len().saturating_mul(2).max(1) {
            let roll = self.topology_rng.gen::<f64>();
            let team_index = self
                .team_cdf
                .partition_point(|cumulative| *cumulative < roll)
                .min(self.teams.len() - 1);
            if eligible[team_index] {
                return Ok(team_index);
            }
        }
        eligible
            .iter()
            .position(|eligible| *eligible)
            .ok_or(WorldError::NoEligiblePerson)
    }

    fn select_person(
        &mut self,
        team_index: usize,
        exclude: Option<PersonKey>,
        whale_only: bool,
        exclude_pending: bool,
    ) -> Result<PersonKey, WorldError> {
        if !whale_only
            && self
                .topology_rng
                .gen_ratio(u32::from(self.recent_target_percent), 100)
            && !self.teams[team_index].recent.is_empty()
        {
            for _ in 0..RECENT_SELECTION_ATTEMPTS {
                let index = self
                    .topology_rng
                    .gen_range(0..self.teams[team_index].recent.len());
                let candidate = self.teams[team_index].recent[index];
                if self.person(candidate).live_index().is_some()
                    && Some(candidate) != exclude
                    && (!exclude_pending
                        || !self.pending_distinct_ids_by_person.contains_key(&candidate))
                {
                    return Ok(candidate);
                }
            }
        }

        let candidates = if whale_only {
            &self.teams[team_index].whales
        } else {
            &self.teams[team_index].live_persons
        };
        if candidates.is_empty() {
            return Err(WorldError::NoEligiblePerson);
        }
        let start = self.topology_rng.gen_range(0..candidates.len());
        for offset in 0..candidates.len() {
            let candidate = candidates[(start + offset) % candidates.len()];
            if Some(candidate) != exclude
                && (!exclude_pending
                    || !self.pending_distinct_ids_by_person.contains_key(&candidate))
            {
                return Ok(candidate);
            }
        }
        Err(WorldError::NoEligiblePerson)
    }

    fn select_distinct_id(&mut self, person_key: PersonKey) -> Result<DistinctIdKey, WorldError> {
        let (head, tail, count) = {
            let person = self.person(person_key);
            (
                person
                    .first_distinct_id()
                    .ok_or(WorldError::NoEligibleDistinctId)?,
                person.last_distinct_id(),
                person.distinct_id_count,
            )
        };
        if count > 1 {
            let tail = tail.ok_or(WorldError::NoEligibleDistinctId)?;
            let next = self
                .distinct_id(head)
                .next()
                .ok_or(WorldError::NoEligibleDistinctId)?;
            self.distinct_id_mut(tail).next = head.0;
            self.distinct_id_mut(head).next = NONE_INDEX;
            let person = self.person_mut(person_key);
            person.first_distinct_id = next.0;
            person.last_distinct_id = head.0;
        }
        Ok(head)
    }

    fn touch_person(&mut self, person_key: PersonKey) {
        if self.recent_capacity_per_team == 0 || self.person(person_key).live_index().is_none() {
            return;
        }
        let team_index = self.person(person_key).team_index as usize;
        let recent = &mut self.teams[team_index].recent;
        recent.push_back(person_key);
        if recent.len() > self.recent_capacity_per_team {
            recent.pop_front();
        }
    }

    fn ensure_whale(&mut self, person_key: PersonKey) {
        let person = self.person(person_key);
        if person.distinct_id_count < WHALE_MIN_FANOUT
            || person.whale_index().is_some()
            || person.live_index().is_none()
        {
            return;
        }
        let team_index = person.team_index as usize;
        let Ok(whale_index) = u32::try_from(self.teams[team_index].whales.len()) else {
            return;
        };
        self.teams[team_index].whales.push(person_key);
        self.person_mut(person_key).whale_index = whale_index;
    }

    fn remove_live_person(&mut self, person_key: PersonKey) {
        let team_index = self.person(person_key).team_index as usize;
        let live_index = self
            .person(person_key)
            .live_index()
            .expect("only live persons can be merged");
        let moved_live = {
            let live_persons = &mut self.teams[team_index].live_persons;
            live_persons.swap_remove(live_index);
            live_persons.get(live_index).copied()
        };
        if let Some(moved) = moved_live {
            self.person_mut(moved).live_index = live_index as u32;
        }

        if let Some(whale_index) = self.person(person_key).whale_index() {
            let moved_whale = {
                let whales = &mut self.teams[team_index].whales;
                whales.swap_remove(whale_index);
                whales.get(whale_index).copied()
            };
            if let Some(moved) = moved_whale {
                self.person_mut(moved).whale_index = whale_index as u32;
            }
        }
        let person = self.person_mut(person_key);
        person.live_index = NONE_INDEX;
        person.whale_index = NONE_INDEX;
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PopulationPerson {
    pub team_id: i32,
    pub person_uuid: Uuid,
    pub version: i64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PopulationDistinctId {
    pub team_id: i32,
    pub person_uuid: Uuid,
    pub distinct_id: Box<str>,
    pub version: i64,
}

#[derive(Debug, Clone, Copy)]
pub struct PopulationView<'a> {
    world: &'a WorldState,
}

impl PopulationView<'_> {
    pub const fn property_bytes(&self) -> usize {
        self.world.property_bytes
    }

    pub const fn property_seed(&self) -> u64 {
        self.world.seed ^ PROPERTY_SEED_MIX
    }

    pub fn persons(&self) -> impl Iterator<Item = PopulationPerson> + '_ {
        self.world
            .persons
            .iter()
            .enumerate()
            .filter_map(|(index, person)| {
                person.live_index().map(|_| {
                    let person_key = PersonKey(index as u32);
                    PopulationPerson {
                        team_id: self.world.teams[person.team_index as usize].team_id,
                        person_uuid: self.world.person_uuid(person_key),
                        version: person.version,
                    }
                })
            })
    }

    pub fn distinct_ids(&self) -> impl Iterator<Item = PopulationDistinctId> + '_ {
        self.world
            .distinct_ids
            .iter()
            .enumerate()
            .filter(|(_, distinct_id)| !distinct_id.is_pending())
            .map(|(index, distinct_id)| {
                let owner = self.world.person(distinct_id.owner);
                PopulationDistinctId {
                    team_id: self.world.teams[owner.team_index as usize].team_id,
                    person_uuid: self.world.person_uuid(distinct_id.owner),
                    distinct_id: self.world.distinct_id_value(DistinctIdKey(index as u32)),
                    version: distinct_id.version,
                }
            })
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[repr(transparent)]
pub struct PersonCreationCount(u64);

impl PersonCreationCount {
    pub const fn new(count: u64) -> Self {
        Self(count)
    }

    pub const fn get(self) -> u64 {
        self.0
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[repr(transparent)]
pub struct DistinctIdAssignmentCount(u64);

impl DistinctIdAssignmentCount {
    pub const fn new(count: u64) -> Self {
        Self(count)
    }

    pub const fn get(self) -> u64 {
        self.0
    }
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize)]
pub struct WorldGrowth {
    pub person_creations: PersonCreationCount,
    pub distinct_id_assignments: DistinctIdAssignmentCount,
}

impl WorldGrowth {
    pub const fn new(
        person_creations: PersonCreationCount,
        distinct_id_assignments: DistinctIdAssignmentCount,
    ) -> Self {
        Self {
            person_creations,
            distinct_id_assignments,
        }
    }
}

impl Default for PersonCreationCount {
    fn default() -> Self {
        Self::new(0)
    }
}

impl Default for DistinctIdAssignmentCount {
    fn default() -> Self {
        Self::new(0)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct WorldMemoryEstimate {
    pub growth: WorldGrowth,
    pub person_count: u64,
    pub expected_distinct_id_count: u64,
    pub person_slot_bytes: usize,
    pub distinct_id_slot_bytes: usize,
    pub person_arena_bytes: u64,
    pub distinct_id_arena_bytes: u64,
    pub live_person_index_bytes: u64,
    pub recent_index_bytes: u64,
    pub whale_index_bytes: u64,
    pub chunk_metadata_bytes: u64,
    pub total_bytes: u64,
}

impl WorldMemoryEstimate {
    pub const fn headroom_bytes(self, limit_bytes: u64) -> Option<u64> {
        limit_bytes.checked_sub(self.total_bytes)
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum WorldError {
    InvalidTeamCount(i32),
    InvalidRecentTargetPercent(u8),
    PopulationTooLarge(usize),
    NoEligiblePerson,
    NoEligibleDistinctId,
    VersionExhausted,
    FanoutExhausted,
    ArenaExhausted(&'static str),
    IndexExhausted(&'static str),
    IdentifierExhausted(&'static str),
    AllocationFailed(&'static str),
    MemoryEstimateOverflow,
    InvalidPendingActivation,
}

impl fmt::Display for WorldError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidTeamCount(team_count) => {
                write!(formatter, "team count must be positive, got {team_count}")
            }
            Self::InvalidRecentTargetPercent(percent) => {
                write!(
                    formatter,
                    "recent target percent must be at most 100, got {percent}"
                )
            }
            Self::PopulationTooLarge(count) => {
                write!(formatter, "population of {count} exceeds the u32 arena")
            }
            Self::NoEligiblePerson => formatter.write_str("no eligible live person"),
            Self::NoEligibleDistinctId => formatter.write_str("no eligible distinct ID"),
            Self::VersionExhausted => formatter.write_str("entity version exhausted"),
            Self::FanoutExhausted => formatter.write_str("person fanout exhausted"),
            Self::ArenaExhausted(kind) => write!(formatter, "{kind} arena exhausted"),
            Self::IndexExhausted(kind) => write!(formatter, "{kind} index exhausted"),
            Self::IdentifierExhausted(kind) => write!(formatter, "{kind} identifier exhausted"),
            Self::AllocationFailed(kind) => write!(formatter, "allocate {kind} index capacity"),
            Self::MemoryEstimateOverflow => formatter.write_str("memory estimate overflowed"),
            Self::InvalidPendingActivation => {
                formatter.write_str("pending world activation is invalid or already applied")
            }
        }
    }
}

impl std::error::Error for WorldError {}

fn increment_version(version: i64) -> Result<i64, WorldError> {
    version.checked_add(1).ok_or(WorldError::VersionExhausted)
}

fn stale_version(version: i64) -> i64 {
    version.saturating_sub(1)
}

fn allocate_zipf_counts(weights: &[f64], total: usize) -> Vec<usize> {
    let total_weight: f64 = weights.iter().sum();
    let exact = weights
        .iter()
        .map(|weight| weight / total_weight * total as f64)
        .collect::<Vec<_>>();
    let mut counts = exact
        .iter()
        .map(|value| value.floor() as usize)
        .collect::<Vec<_>>();
    let assigned: usize = counts.iter().sum();
    let mut remainders = exact
        .iter()
        .enumerate()
        .map(|(index, value)| (index, value.fract()))
        .collect::<Vec<_>>();
    remainders.sort_by(|left, right| {
        right
            .1
            .total_cmp(&left.1)
            .then_with(|| left.0.cmp(&right.0))
    });
    for (index, _) in remainders.into_iter().take(total.saturating_sub(assigned)) {
        counts[index] += 1;
    }
    counts
}

fn fanout_for_roll(bucket_roll: u32, within_bucket_roll: u64) -> u32 {
    let bucket = FANOUT_BUCKETS
        .iter()
        .find(|bucket| bucket_roll < bucket.upper_roll_exclusive)
        .unwrap_or(&FANOUT_BUCKETS[FANOUT_BUCKETS.len() - 1]);
    let width = u64::from(bucket.max - bucket.min + 1);
    bucket.min + (within_bucket_roll % width) as u32
}

fn whale_bucket_rolls() -> u64 {
    let previous_upper = FANOUT_BUCKETS[FANOUT_BUCKETS.len() - 2].upper_roll_exclusive;
    u64::from(FANOUT_ROLLS - previous_upper)
}

fn expected_distinct_id_count(person_count: u64) -> Result<u64, WorldError> {
    let weighted_doubled_fanout =
        FANOUT_BUCKETS
            .iter()
            .enumerate()
            .try_fold(0u64, |total, (index, bucket)| {
                let lower = if index == 0 {
                    0
                } else {
                    FANOUT_BUCKETS[index - 1].upper_roll_exclusive
                };
                let rolls = u64::from(bucket.upper_roll_exclusive - lower);
                let doubled_mean = u64::from(bucket.min + bucket.max);
                total
                    .checked_add(
                        rolls
                            .checked_mul(doubled_mean)
                            .ok_or(WorldError::MemoryEstimateOverflow)?,
                    )
                    .ok_or(WorldError::MemoryEstimateOverflow)
            })?;
    let numerator = person_count
        .checked_mul(weighted_doubled_fanout)
        .ok_or(WorldError::MemoryEstimateOverflow)?;
    div_ceil(numerator, u64::from(FANOUT_ROLLS) * 2)
}

fn chunk_count(items: u64) -> Result<u64, WorldError> {
    div_ceil(items, ARENA_CHUNK_CAPACITY as u64)
}

fn chunk_allocation_bytes(chunks: u64, item_bytes: usize) -> Result<u64, WorldError> {
    checked_product(
        checked_product(chunks, ARENA_CHUNK_CAPACITY as u64)?,
        item_bytes as u64,
    )
}

fn checked_product(left: u64, right: u64) -> Result<u64, WorldError> {
    left.checked_mul(right)
        .ok_or(WorldError::MemoryEstimateOverflow)
}

fn div_ceil(numerator: u64, denominator: u64) -> Result<u64, WorldError> {
    let adjusted = numerator
        .checked_add(denominator - 1)
        .ok_or(WorldError::MemoryEstimateOverflow)?;
    Ok(adjusted / denominator)
}

/// Generate a JSONB properties object padded to approximately `target_bytes`.
pub fn generate_properties(rng: &mut impl Rng, target_bytes: usize) -> Value {
    const KEYS: &[&str] = &[
        "$browser",
        "$os",
        "$initial_referrer",
        "$initial_referring_domain",
        "$geoip_city_name",
        "$geoip_country_code",
        "$geoip_time_zone",
        "email",
        "name",
        "plan",
        "company",
        "role",
        "signup_date",
        "last_login",
    ];

    let mut object = serde_json::Map::with_capacity(KEYS.len() + 1);
    for key in KEYS {
        let value_len = rng.gen_range(4..30);
        let value = (0..value_len)
            .map(|_| rng.gen_range(b'a'..=b'z') as char)
            .collect::<String>();
        object.insert((*key).to_owned(), Value::String(value));
    }
    let current_bytes = Value::Object(object.clone()).to_string().len();
    if current_bytes < target_bytes {
        let value_len = (target_bytes - current_bytes).saturating_sub(12);
        let padding = (0..value_len)
            .map(|_| rng.gen_range(b'a'..=b'z') as char)
            .collect::<String>();
        object.insert("_pad".to_owned(), Value::String(padding));
    }
    Value::Object(object)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::benchmark::ops::PhaseId;

    const TEST_PHASE: PhaseId = PhaseId::new(1);

    fn at(nanos: u64) -> NanosSincePhaseStart {
        at_in_phase(TEST_PHASE, nanos)
    }

    fn at_in_phase(phase_id: PhaseId, nanos: u64) -> NanosSincePhaseStart {
        NanosSincePhaseStart::from_nanos(phase_id, nanos)
    }

    fn empty_world() -> WorldState {
        WorldState::new(WorldConfig {
            seed: 7,
            team_count: 1,
            initial_person_count: 0,
            recent_capacity_per_team: 8,
            recent_target_percent: 50,
            property_bytes: 32,
        })
        .expect("valid world")
    }

    #[test]
    fn versions_survive_phases_and_full_merge_matches_producer_versions() {
        let mut world = empty_world();
        world.create_person(0, 3).expect("first person");

        let update_one = world
            .resolve_person_upsert(at(10), ReplayMode::Fresh)
            .expect("first update");
        let update_two = world
            .resolve_person_upsert(at_in_phase(PhaseId::new(2), 0), ReplayMode::Fresh)
            .expect("next phase update");
        let version = |descriptor: &OpDescriptor| match &descriptor.payload {
            OpPayload::PersonUpsert(payload) => payload.version,
            _ => panic!("expected person upsert"),
        };
        assert!(version(&update_two) > version(&update_one));

        world.create_person(0, 2).expect("second person");
        let before = world
            .persons
            .iter()
            .enumerate()
            .filter(|(_, person)| person.live_index().is_some())
            .map(|(index, person)| {
                (
                    world.person_uuid(PersonKey(index as u32)),
                    person.version,
                    person.distinct_id_count,
                )
            })
            .collect::<Vec<_>>();
        let merge = world.resolve_full_merge(at(20)).expect("full merge");
        let payload = match merge.payload {
            OpPayload::FullMerge(payload) => payload,
            _ => panic!("expected full merge"),
        };

        let (_, source_version, source_fanout) = before
            .iter()
            .find(|(uuid, _, _)| *uuid == payload.source_person_uuid)
            .expect("source existed");
        let (_, target_version, _) = before
            .iter()
            .find(|(uuid, _, _)| *uuid == payload.target_person_uuid)
            .expect("target existed");
        assert_eq!(payload.distinct_id_moves.len(), *source_fanout as usize);
        assert_eq!(
            payload.target_version,
            (*source_version).max(*target_version) + 1
        );
        assert_eq!(payload.source_tombstone_version, source_version + 100);
        assert_eq!(world.live_person_count(), 1);

        let source_key = before
            .iter()
            .position(|(uuid, _, _)| *uuid == payload.source_person_uuid)
            .map(|index| PersonKey(index as u32))
            .expect("source key");
        let target_key = before
            .iter()
            .position(|(uuid, _, _)| *uuid == payload.target_person_uuid)
            .map(|index| PersonKey(index as u32))
            .expect("target key");
        assert_eq!(
            world.person(source_key).version,
            payload.source_tombstone_version
        );
        assert_eq!(world.person(target_key).version, payload.target_version);
        assert!(world.person(source_key).live_index().is_none());
        assert_eq!(world.person(source_key).distinct_id_count, 0);

        let population = world.population();
        for moved in &payload.distinct_id_moves {
            let mapping = population
                .distinct_ids()
                .find(|mapping| mapping.distinct_id == moved.distinct_id)
                .expect("moved mapping");
            assert_eq!(mapping.person_uuid, payload.target_person_uuid);
        }
    }

    #[test]
    fn read_misses_and_fanout_edges_are_explicit() {
        assert_eq!(fanout_for_roll(0, 0), 1);
        assert_eq!(fanout_for_roll(94_999, u64::MAX), 1);
        assert_eq!(fanout_for_roll(95_000, 0), 2);
        assert_eq!(fanout_for_roll(99_989, u64::MAX), 2);
        assert_eq!(fanout_for_roll(99_990, 0), 3);
        assert_eq!(fanout_for_roll(99_998, 97), 100);
        assert_eq!(fanout_for_roll(99_999, 0), 101);
        assert_eq!(fanout_for_roll(99_999, 899), 1_000);

        let mut world = empty_world();
        world.create_person(0, 101).expect("whale person");
        world.create_person(0, 1).expect("merge target");
        let miss = world
            .resolve_read(at(0), ReadMode::Miss)
            .expect("read miss");
        let miss_payload = match miss.payload {
            OpPayload::CanonicalRead(payload) => payload,
            _ => panic!("expected read"),
        };
        assert_eq!(miss_payload.expectation, ReadExpectation::Miss);
        assert!(world
            .population()
            .distinct_ids()
            .all(|mapping| mapping.distinct_id != miss_payload.distinct_id));

        let whale_merge = world.resolve_whale_merge(at(1)).expect("whale merge");
        let merge_payload = match whale_merge.payload {
            OpPayload::FullMerge(payload) => payload,
            _ => panic!("expected merge"),
        };
        assert_eq!(merge_payload.shape, MergeShape::Whale);
        assert_eq!(merge_payload.distinct_id_moves.len(), 101);
    }

    #[test]
    fn forty_five_million_person_estimate_stays_below_five_gibibytes() {
        let config = WorldConfig {
            initial_person_count: 45_000_000,
            ..WorldConfig::default()
        };
        let estimate = WorldState::estimate_initial_memory(&config).expect("memory estimate");

        assert_eq!(estimate.person_slot_bytes, 32);
        assert_eq!(estimate.distinct_id_slot_bytes, 16);
        assert_eq!(size_of::<PersonKey>(), 4);
        assert_eq!(estimate.expected_distinct_id_count, 47_697_300);
        assert!(estimate.total_bytes < 5 * 1024 * 1024 * 1024);
    }

    #[test]
    fn memory_estimate_accounts_for_growth_and_creation_primary_ids() {
        let config = WorldConfig::default();
        let initial = WorldState::estimate_initial_memory(&config).expect("initial estimate");
        assert_eq!(
            initial,
            WorldState::estimate_memory(&config, WorldGrowth::default())
                .expect("zero-growth estimate")
        );

        let growth = WorldGrowth::new(
            PersonCreationCount::new(1_000),
            DistinctIdAssignmentCount::new(2_000),
        );
        let grown = WorldState::estimate_memory(&config, growth).expect("growth estimate");

        assert_eq!(grown.person_count, initial.person_count + 1_000);
        assert_eq!(
            initial.recent_index_bytes,
            config.team_count as u64
                * config.recent_capacity_per_team as u64
                * size_of::<PersonKey>() as u64
        );
        assert_eq!(
            grown.expected_distinct_id_count,
            initial.expected_distinct_id_count + 3_000
        );
        assert!(grown.total_bytes >= initial.total_bytes);
        assert!(
            initial.headroom_bytes(grown.total_bytes).expect("headroom")
                >= grown.headroom_bytes(grown.total_bytes).expect("exact fit")
        );
        assert!(grown.headroom_bytes(grown.total_bytes - 1).is_none());
    }

    #[test]
    fn person_growth_is_reserved_before_the_workload() {
        let mut world = WorldState::new(WorldConfig {
            team_count: 4,
            initial_person_count: 100,
            ..WorldConfig::default()
        })
        .expect("world");
        world
            .reserve_person_growth(PersonCreationCount::new(50))
            .expect("growth reservation");

        let reserved_slots = world
            .teams
            .iter()
            .map(|team| team.live_persons.capacity() - team.live_persons.len())
            .sum::<usize>();
        assert!(reserved_slots >= 50);
        assert!(world.growth_reservation_enabled);
    }

    #[test]
    fn distinct_id_selection_rotates_the_intrusive_list() {
        let mut world = empty_world();
        let person = world.create_person(0, 3).expect("person");
        let first = world
            .person(person)
            .first_distinct_id()
            .expect("first distinct ID");
        let second = world.distinct_id(first).next().expect("second distinct ID");
        let third = world.distinct_id(second).next().expect("third distinct ID");

        let selected = (0..4)
            .map(|_| {
                world
                    .select_distinct_id(person)
                    .expect("selected distinct ID")
            })
            .collect::<Vec<_>>();

        assert_eq!(selected, vec![first, second, third, first]);
        assert_eq!(world.person(person).first_distinct_id(), Some(second));
        assert_eq!(world.person(person).last_distinct_id(), Some(first));
    }

    #[test]
    fn person_creation_preflights_distinct_id_capacity() {
        let mut world = empty_world();
        let person_count = world.persons.len();
        let live_count = world.teams[0].live_persons.len();
        let recent_count = world.teams[0].recent.len();
        world.distinct_ids.len = u32::MAX;

        assert_eq!(
            world.create_person(0, 1),
            Err(WorldError::ArenaExhausted("distinct ID"))
        );
        assert_eq!(world.persons.len(), person_count);
        assert_eq!(world.teams[0].live_persons.len(), live_count);
        assert_eq!(world.teams[0].recent.len(), recent_count);
    }

    #[test]
    fn pending_creation_is_invisible_until_both_writes_activate_it() {
        let mut world = empty_world();
        let creation = world.resolve_creation(at(0)).expect("pending creation");
        let distinct_id = match &creation.distinct_id_assignment.payload {
            OpPayload::DistinctIdAssignment(payload) => payload.distinct_id.clone(),
            _ => panic!("expected distinct ID assignment"),
        };

        assert_eq!(world.live_person_count(), 0);
        assert_eq!(world.population().persons().count(), 0);
        assert_eq!(world.population().distinct_ids().count(), 0);
        assert_eq!(
            world.resolve_read(at(1), ReadMode::Hit),
            Err(WorldError::NoEligiblePerson)
        );

        world
            .activate_creation(creation.activation)
            .expect("both writes completed");
        let read = world.resolve_read(at(2), ReadMode::Hit).expect("live read");
        let read_distinct_id = match read.payload {
            OpPayload::CanonicalRead(payload) => payload.distinct_id,
            _ => panic!("expected canonical read"),
        };
        assert_eq!(read_distinct_id, distinct_id);
        assert_eq!(world.live_person_count(), 1);
        assert_eq!(
            world.activate_creation(creation.activation),
            Err(WorldError::InvalidPendingActivation)
        );
    }

    #[test]
    fn new_distinct_id_is_invisible_until_its_write_activates_it() {
        let mut world = empty_world();
        world.create_person(0, 1).expect("live person");
        let assignment = world
            .resolve_distinct_id_assignment(at(0), AssignmentMode::New)
            .expect("pending assignment");
        let pending_distinct_id = match &assignment.operation.payload {
            OpPayload::DistinctIdAssignment(payload) => payload.distinct_id.clone(),
            _ => panic!("expected distinct ID assignment"),
        };

        assert_eq!(world.population().distinct_ids().count(), 1);
        let before = world
            .resolve_read(at(1), ReadMode::Hit)
            .expect("existing read");
        assert_ne!(
            match before.payload {
                OpPayload::CanonicalRead(payload) => payload.distinct_id,
                _ => panic!("expected canonical read"),
            },
            pending_distinct_id
        );

        world
            .activate_distinct_id(assignment.activation.expect("new assignment token"))
            .expect("assignment completed");
        assert_eq!(world.population().distinct_ids().count(), 2);
        let reads = (0..2)
            .map(|offset| {
                let read = world
                    .resolve_read(at(2 + offset), ReadMode::Hit)
                    .expect("live read");
                match read.payload {
                    OpPayload::CanonicalRead(payload) => payload.distinct_id,
                    _ => panic!("expected canonical read"),
                }
            })
            .collect::<Vec<_>>();
        assert!(reads.contains(&pending_distinct_id));
    }

    #[test]
    fn fresh_existing_assignment_reuses_a_slot_and_advances_its_version() {
        let mut world = empty_world();
        world.create_person(0, 1).expect("live person");
        let before = world
            .population()
            .distinct_ids()
            .next()
            .expect("existing distinct ID");

        let assignment = world
            .resolve_distinct_id_assignment(at(0), AssignmentMode::FreshExisting)
            .expect("fresh existing assignment");
        let payload = match assignment.operation.payload {
            OpPayload::DistinctIdAssignment(payload) => payload,
            _ => panic!("expected distinct ID assignment"),
        };

        assert!(assignment.activation.is_none());
        assert_eq!(world.distinct_id_count(), 1);
        assert_eq!(payload.distinct_id, before.distinct_id);
        assert_eq!(payload.version, before.version + 1);
    }

    #[test]
    fn merge_does_not_remove_the_owner_of_a_pending_distinct_id() {
        let mut world = empty_world();
        world.create_person(0, 1).expect("first live person");
        world.create_person(0, 1).expect("second live person");
        let assignment = world
            .resolve_distinct_id_assignment(at(0), AssignmentMode::New)
            .expect("pending assignment");
        let (pending_owner, pending_distinct_id) = match &assignment.operation.payload {
            OpPayload::DistinctIdAssignment(payload) => {
                (payload.person_uuid, payload.distinct_id.clone())
            }
            _ => panic!("expected distinct ID assignment"),
        };

        let merge = world.resolve_full_merge(at(1)).expect("merge");
        let merge = match merge.payload {
            OpPayload::FullMerge(payload) => payload,
            _ => panic!("expected merge"),
        };
        assert_ne!(merge.source_person_uuid, pending_owner);
        assert_eq!(merge.target_person_uuid, pending_owner);

        world
            .activate_distinct_id(assignment.activation.expect("pending assignment token"))
            .expect("assignment completed");
        let mapping = world
            .population()
            .distinct_ids()
            .find(|mapping| mapping.distinct_id == pending_distinct_id)
            .expect("activated mapping");
        assert_eq!(mapping.person_uuid, pending_owner);
    }

    #[test]
    fn chunk_growth_keeps_existing_allocations_stable() {
        let mut arena = ChunkedArena::new();
        arena.push(0u32).expect("first item");
        let first_address: *const u32 = arena.get(0);
        for value in 1..=ARENA_CHUNK_CAPACITY as u32 {
            arena.push(value).expect("arena item");
        }

        assert_eq!(arena.chunk_count(), 2);
        let current_first_address: *const u32 = arena.get(0);
        assert_eq!(first_address, current_first_address);
        assert_eq!(
            *arena.get(ARENA_CHUNK_CAPACITY as u32),
            ARENA_CHUNK_CAPACITY as u32
        );
    }
}
