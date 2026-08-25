//! Interactive explorer for the handoff-protocol model.
//!
//! ```sh
//! cargo run -p personhog-stateright -- current
//! cargo run -p personhog-stateright -- current-zombie
//! cargo run -p personhog-stateright -- epoch-fenced
//! ```
//!
//! Serves the Stateright web UI at http://localhost:3000 for stepping
//! through counterexample traces state by state.

use clap::{Parser, ValueEnum};

use personhog_stateright::model::{ClaimDetection, HandoffModel, Variant, WarmOrder};
use stateright::Model;

#[derive(Parser)]
struct Args {
    #[arg(value_enum)]
    scenario: Scenario,
}

#[derive(Clone, Copy, Debug, ValueEnum)]
enum Scenario {
    /// Failures without zombie windows.
    Current,
    /// The double-zombie residual, with counterexamples.
    CurrentZombie,
    /// The epoch-fencing fix.
    EpochFenced,
    /// The rejected warm ordering (read before fence), with
    /// counterexamples.
    EpochFencedReadFirst,
}

fn main() {
    let args = Args::parse();
    let (variant, warm_order, crashes, zombie_window) = match args.scenario {
        Scenario::Current => (Variant::Current, WarmOrder::FenceFirst, 1, 0),
        Scenario::CurrentZombie => (Variant::Current, WarmOrder::FenceFirst, 1, 1),
        Scenario::EpochFenced => (Variant::EpochFenced, WarmOrder::FenceFirst, 1, 1),
        Scenario::EpochFencedReadFirst => (Variant::EpochFenced, WarmOrder::ReadFirst, 2, 1),
    };

    let model = HandoffModel {
        pods: 2,
        routers: 2,
        late_routers: 0,
        partitions: 1,
        variant,
        warm_order,
        lease_gated_reads: false,
        claim_recovers: true,
        claim_detection: ClaimDetection::Prompt,
        writes: 2,
        reads: 1,
        crashes,
        rejoins: 0,
        router_joins: 0,
        zombie_window,
        hold_pods: 0,
        cancels: 0,
        probes: false,
    };
    println!("exploring {:?} at http://localhost:3000 …", args.scenario);
    model.checker().serve("localhost:3000");
}
