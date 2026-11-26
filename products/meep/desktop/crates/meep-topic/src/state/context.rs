use super::*;
use std::collections::HashSet;

impl TopicState {
    pub(super) fn select_github_repository(
        &mut self,
        previous: Option<WatchId>,
        id: WatchId,
        repository: String,
        now: DateTime<Utc>,
    ) -> Transition {
        let mut sources = self.topic.context_sources.clone();
        let current = sources
            .iter()
            .position(|s| s.connection == "github" && s.kind == "repository");
        if current.map(|i| sources[i].id) != previous {
            return Ok(vec![]);
        }
        if let Some(i) = current {
            sources.remove(i);
        }
        sources.push(Watch {
            id,
            connection: "github".into(),
            kind: "repository".into(),
            label: repository.clone(),
            key: repository,
        });
        self.set_context_sources(sources, now)
    }

    /// IDs named by active or queued human fact reviews, including withdrawn evidence.
    pub fn disputed_facts(&self) -> std::collections::BTreeSet<FactId> {
        let mut ids = std::collections::BTreeSet::new();
        for thread in &self.threads {
            let active = match &thread.state {
                ThreadState::NeedsYou { suggestions, .. } => suggestions.as_slice(),
                _ => &[],
            };
            for choice in active
                .iter()
                .chain(thread.pending_questions.iter().flat_map(|q| &q.suggestions))
            {
                if let Suggestion::ResolveFacts { changed, other, .. } = choice {
                    ids.extend([*changed, *other]);
                }
            }
        }
        ids
    }

    /// Check the evidence on which an external action says its result depends.
    pub fn check_action_evidence(&self, action: &Action) -> Result<(), TopicError> {
        let disputes = self.disputed_facts();
        let Some(facts) = &action.depends_on_facts else {
            return if disputes.is_empty() {
                Ok(())
            } else {
                Err(TopicError::DisputedEvidence)
            };
        };
        for id in facts {
            if disputes.contains(id) {
                return Err(TopicError::DisputedEvidence);
            }
            if !self
                .topic
                .facts
                .iter()
                .any(|f| f.id == *id && f.is_current())
            {
                return Err(TopicError::RetiredEvidence(*id));
            }
        }
        Ok(())
    }

    fn validate_fact(&self, fact: &Fact) -> Result<(), TopicError> {
        if self
            .history
            .iter()
            .any(|c| c.kind == ChangeKind::FactAdded(fact.id))
            || self.topic.facts.iter().any(|f| f.id == fact.id)
        {
            return Err(TopicError::DuplicateId(fact.id.to_string()));
        }
        if !fact.is_current() {
            return Err(TopicError::Superseded(fact.id));
        }
        if let Some(id) = fact.provenance.thread {
            self.thread_index(id)?;
        }
        Ok(())
    }

    /// Records a new assertion and its evidence.
    pub fn add_fact(&mut self, fact: Fact, now: DateTime<Utc>) -> Transition {
        self.validate_fact(&fact)?;
        let id = fact.id;
        let text = format!("Learned “{}”.", fact.text);
        let actor = fact.provenance.thread.map_or(Actor::User, Actor::Inbox);
        self.topic.facts.push(fact);
        Ok(self.record(now, actor, Ref::Fact(id), text, [ChangeKind::FactAdded(id)]))
    }

    /// Retains the old assertion and links it to a fresh replacement in one transition.
    pub fn supersede_fact(&mut self, old: FactId, new: Fact, now: DateTime<Utc>) -> Transition {
        let i = self.fact_index(old)?;
        if !self.topic.facts[i].is_current() {
            return Err(TopicError::Superseded(old));
        }
        self.validate_fact(&new)?;
        let id = new.id;
        let text = format!(
            "Replaced “{}” with “{}”.",
            self.topic.facts[i].text, new.text
        );
        let actor = new.provenance.thread.map_or(Actor::User, Actor::Inbox);
        self.topic.facts[i].superseded_by = Some(id);
        self.topic.facts.push(new);
        Ok(self.record(
            now,
            actor,
            Ref::Fact(old),
            text,
            [
                ChangeKind::FactAdded(id),
                ChangeKind::FactSuperseded(old, id),
            ],
        ))
    }

    /// Removes a fact from context. Past activity and digest counts retain its history.
    pub fn remove_fact(&mut self, id: FactId, now: DateTime<Utc>) -> Transition {
        let i = self.fact_index(id)?;
        if self.topic.facts[i].withdrawn_at.is_some() {
            return Err(TopicError::UnknownFact(id));
        }
        self.removed_facts.insert(id, self.topic.facts[i].clone());
        let text = format!("Removed the fact “{}”.", self.topic.facts[i].text);
        if self
            .topic
            .facts
            .iter()
            .any(|f| f.superseded_by == Some(id) || f.invalidated_by == Some(id))
        {
            self.topic.facts[i].withdrawn_at = Some(now);
        } else {
            self.topic.facts.remove(i);
        }
        Ok(self.record(
            now,
            Actor::User,
            Ref::Fact(id),
            text,
            [ChangeKind::FactRemoved(id)],
        ))
    }

    /// Validate a review against current assertions before applying a model or human decision.
    pub fn can_resolve_facts(
        &self,
        changed: FactId,
        other: FactId,
        resolution: FactResolution,
    ) -> bool {
        let current = |id| {
            self.topic
                .facts
                .iter()
                .any(|f| f.id == id && f.is_current())
        };
        let valid_change = if resolution.withdrawal() {
            !current(changed)
                && (self.topic.facts.iter().any(|fact| fact.id == changed)
                    || self
                        .history
                        .iter()
                        .any(|c| c.kind == ChangeKind::FactRemoved(changed)))
        } else {
            current(changed)
        };
        changed != other && current(other) && valid_change
    }

    /// Apply reconciliation to existing IDs, retaining the assertions and their provenance.
    pub fn resolve_facts(
        &mut self,
        changed: FactId,
        other: FactId,
        resolution: FactResolution,
        actor: Actor,
        now: DateTime<Utc>,
    ) -> Transition {
        if !self.can_resolve_facts(changed, other, resolution) {
            return Err(TopicError::StaleFactReview);
        }
        let (loser, winner) = match resolution {
            FactResolution::KeepChanged => (other, changed),
            FactResolution::KeepExisting => (changed, other),
            FactResolution::RetireDependent => (other, changed),
            FactResolution::KeepBoth | FactResolution::KeepDependent => return Ok(vec![]),
        };
        let index = self.fact_index(loser)?;
        let (kind, text) = if resolution.withdrawal() {
            let fact = &mut self.topic.facts[index];
            fact.invalidated_by = Some(winner);
            (
                ChangeKind::FactInvalidated(loser, winner),
                format!("Retired “{}” after its evidence was withdrawn.", fact.text),
            )
        } else {
            let winner_index = self.fact_index(winner)?;
            let text = format!(
                "Replaced “{}” with “{}”.",
                self.topic.facts[index].text, self.topic.facts[winner_index].text
            );
            self.topic.facts[index].superseded_by = Some(winner);
            (ChangeKind::FactSuperseded(loser, winner), text)
        };
        Ok(self.record(now, actor, Ref::Fact(loser), text, [kind]))
    }

    /// Replaces the topic's mission.
    pub fn set_mission(&mut self, mission: impl Into<String>, now: DateTime<Utc>) -> Transition {
        self.topic.mission = mission.into();
        Ok(self.record(
            now,
            Actor::User,
            Ref::Topic,
            format!("Set the mission to “{}”.", self.topic.mission),
            [ChangeKind::TopicUpdated(self.topic.id)],
        ))
    }

    /// Adds a new objective.
    pub fn add_goal(&mut self, goal: Goal, now: DateTime<Utc>) -> Transition {
        let id = goal.id;
        if self.topic.goals.iter().any(|g| g.id == id) {
            return Err(TopicError::DuplicateId(id.to_string()));
        }
        validate_progress(id, goal.progress.as_ref())?;
        let text = format!("Added the goal “{}”.", goal.text);
        self.topic.goals.push(goal);
        Ok(self.record(
            now,
            Actor::User,
            Ref::Topic,
            text,
            [ChangeKind::GoalAdded(id)],
        ))
    }

    /// Sets or clears the latest measurement for a goal.
    pub fn update_goal_progress(
        &mut self,
        id: GoalId,
        progress: Option<Progress>,
        now: DateTime<Utc>,
    ) -> Transition {
        let goal = self
            .topic
            .goals
            .iter_mut()
            .find(|g| g.id == id)
            .ok_or(TopicError::UnknownGoal(id))?;
        validate_progress(id, progress.as_ref())?;
        goal.progress = progress;
        let text = format!("Updated progress on “{}”.", goal.text);
        Ok(self.record(
            now,
            Actor::User,
            Ref::Topic,
            text,
            [ChangeKind::GoalUpdated(id)],
        ))
    }

    /// Appends a rule with higher precedence than earlier rules.
    pub fn add_rule(&mut self, rule: Rule, now: DateTime<Utc>) -> Transition {
        let id = rule.id;
        if self.topic.rules.iter().any(|r| r.id == id)
            || self
                .history
                .iter()
                .any(|c| c.kind == ChangeKind::RuleRemoved(id))
        {
            return Err(TopicError::DuplicateId(id.to_string()));
        }
        if let Some(task) = rule.from_task {
            self.task_index(task)?;
        }
        let text = format!("Added the rule “{}”", rule.text);
        self.topic.rules.push(rule);
        Ok(self.record(
            now,
            Actor::User,
            Ref::Rule(id),
            text,
            [ChangeKind::RuleAdded(id)],
        ))
    }

    /// Removes a rule from future policy decisions.
    pub fn remove_rule(&mut self, id: RuleId, now: DateTime<Utc>) -> Transition {
        let i = self
            .topic
            .rules
            .iter()
            .position(|r| r.id == id)
            .ok_or(TopicError::UnknownRule(id))?;
        let rule = self.topic.rules.remove(i);
        self.removed_rules
            .retain(|_, (at, _, _)| *at > now - chrono::TimeDelta::days(30));
        self.removed_rules.insert(id, (now, i, rule.clone()));
        Ok(self.record(
            now,
            Actor::User,
            Ref::Rule(id),
            format!("Removed the rule “{}”", rule.text),
            [ChangeKind::RuleRemoved(id)],
        ))
    }

    /// Remove the routine and its source subscriptions from the topic.
    pub fn remove_workflow(&mut self, binding: &RoutineBinding, now: DateTime<Utc>) -> Transition {
        let index = self
            .topic
            .routines
            .iter()
            .position(|r| r.binding.same_workflow(binding))
            .ok_or_else(|| TopicError::UnknownRoutine(binding.id.clone()))?;
        self.topic.routines.remove(index);
        if self.topic.default_sort.as_ref() == Some(&binding.id) {
            self.topic.default_sort = None;
        }
        Ok(self.record(
            now,
            Actor::User,
            Ref::Routine(binding.id.clone()),
            format!("Deleted routine “{}”.", binding.name),
            [ChangeKind::TopicUpdated(self.topic.id)],
        ))
    }

    /// Make an activated workflow the default and transfer only the built-in sorter's sources.
    pub fn install_default_sort(&mut self, routine: &str, now: DateTime<Utc>) -> Transition {
        let mut watches = self
            .topic
            .routines
            .iter()
            .find(|r| r.binding.id == routine)
            .ok_or_else(|| TopicError::UnknownRoutine(routine.into()))?
            .binding
            .watches
            .clone();
        watches.append(&mut self.topic.fallback.binding.watches);
        self.assign_watches(routine, watches)?;
        self.topic.default_sort = Some(routine.into());
        Ok(self.record(
            now,
            Actor::Routine(routine.into()),
            Ref::Routine(routine.into()),
            "Activated Sort inbox as the topic's default source routine.".into(),
            [ChangeKind::TopicUpdated(self.topic.id)],
        ))
    }

    /// Replace only the default sorter's subscriptions.
    pub fn set_watch(&mut self, watches: Vec<Watch>, now: DateTime<Utc>) -> Transition {
        validate_watches(&watches)?;
        if self.topic.default_sort.is_none() {
            self.topic.fallback.enabled = true;
        }
        let default = self.topic.default_sort.clone();
        let other: HashSet<_> = self
            .topic
            .destinations()
            .filter(|r| !r.binding.is_default_sorter(default.as_deref()))
            .flat_map(|r| r.binding.watches.iter().map(|w| w.id))
            .collect();
        *self.topic.default_watches_mut() = watches
            .into_iter()
            .filter(|w| !other.contains(&w.id))
            .collect();
        Ok(self.watches_changed(now))
    }

    /// Replace the topic-wide selection, keeping retained subscriptions on their owners.
    pub fn set_topic_watches(&mut self, watches: Vec<Watch>, now: DateTime<Utc>) -> Transition {
        validate_watches(&watches)?;
        let mut remaining = watches;
        let default = self.topic.default_sort.clone();
        for info in self
            .topic
            .destinations_mut()
            .filter(|r| !r.binding.is_default_sorter(default.as_deref()))
        {
            let ids: HashSet<_> = info.binding.watches.iter().map(|w| w.id).collect();
            let (owned, rest) = remaining.into_iter().partition(|w| ids.contains(&w.id));
            info.binding.watches = owned;
            remaining = rest;
        }
        *self.topic.default_watches_mut() = remaining;
        Ok(self.watches_changed(now))
    }

    /// Replace passive context references without changing subscriptions.
    pub fn set_context_sources(&mut self, sources: Vec<Watch>, now: DateTime<Utc>) -> Transition {
        validate_watches(&sources)?;
        self.topic.context_sources = sources;
        Ok(self.record(
            now,
            Actor::User,
            Ref::Topic,
            "Updated the topic’s context sources.".into(),
            [ChangeKind::TopicUpdated(self.topic.id)],
        ))
    }

    /// Add a passive reference, preserving other references.
    pub fn add_context_source(&mut self, source: Watch, now: DateTime<Utc>) -> Transition {
        if self.topic.context_sources.iter().any(|w| {
            w.connection == source.connection && w.kind == source.kind && w.key == source.key
        }) {
            return Ok(vec![]);
        }
        let mut sources = self.topic.context_sources.clone();
        sources.push(source);
        self.set_context_sources(sources, now)
    }

    /// Remove a passive reference without changing any routine subscription.
    pub fn remove_context_source(&mut self, source: WatchId, now: DateTime<Utc>) -> Transition {
        let sources = self
            .topic
            .context_sources
            .iter()
            .filter(|w| w.id != source)
            .cloned()
            .collect();
        self.set_context_sources(sources, now)
    }

    /// Replace a binding's subscriptions, atomically moving matching IDs from other owners.
    pub fn set_routine_watches(
        &mut self,
        routine: &str,
        watches: Vec<Watch>,
        now: DateTime<Utc>,
    ) -> Transition {
        self.assign_watches(routine, watches)?;
        if routine == self.topic.fallback.binding.id {
            self.topic.fallback.enabled = true;
        }
        Ok(self.watches_changed(now))
    }

    pub(super) fn assign_watches(
        &mut self,
        routine: &str,
        watches: Vec<Watch>,
    ) -> Result<(), TopicError> {
        let ids = validate_watches(&watches)?;
        if !self.topic.destinations().any(|r| r.binding.id == routine) {
            return Err(TopicError::UnknownRoutine(routine.into()));
        }
        for r in self.topic.destinations_mut() {
            if r.binding.id == routine {
                r.binding.watches = watches.clone();
            } else {
                r.binding.watches.retain(|w| !ids.contains(&w.id));
            }
        }
        Ok(())
    }

    fn watches_changed(&mut self, now: DateTime<Utc>) -> Vec<Change> {
        self.record(
            now,
            Actor::User,
            Ref::Topic,
            "Updated the topic’s watches.".into(),
            [ChangeKind::TopicUpdated(self.topic.id)],
        )
    }
}

pub(super) fn validate_watches(watches: &[Watch]) -> Result<HashSet<WatchId>, TopicError> {
    let mut ids = HashSet::new();
    for watch in watches {
        if !ids.insert(watch.id) {
            return Err(TopicError::DuplicateId(watch.id.to_string()));
        }
    }
    Ok(ids)
}

fn validate_progress(id: GoalId, progress: Option<&Progress>) -> Result<(), TopicError> {
    let valid = match progress {
        None => true,
        Some(Progress::Target {
            current, target, ..
        }) => current.is_finite() && target.is_finite(),
        Some(Progress::Guardrail {
            current, low, high, ..
        }) => current.is_finite() && low.is_finite() && high.is_finite() && low <= high,
    };
    if valid {
        Ok(())
    } else {
        Err(TopicError::InvalidProgress(id))
    }
}
