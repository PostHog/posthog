//! Interactive explorer for the handoff-protocol model.
//!
//! ```sh
//! cargo run -p personhog-stateright -- fenced
//! cargo run -p personhog-stateright -- fenced-zombie
//! cargo run -p personhog-stateright -- fenced-read-first
//! ```
//!
//! Serves the Stateright web UI at http://localhost:3000 for stepping
//! through counterexample traces state by state.

use clap::{Parser, ValueEnum};

use personhog_stateright::model::{ClaimDetection, HandoffModel, WarmOrder};
use stateright::Model;

#[derive(Parser)]
struct Args {
    #[arg(value_enum)]
    scenario: Scenario,
}

#[derive(Clone, Copy, Debug, ValueEnum)]
enum Scenario {
    /// Failures without zombie windows.
    Fenced,
    /// A zombie window, which epoch fencing closes.
    FencedZombie,
    /// The rejected warm ordering (read before fence), with
    /// counterexamples.
    FencedReadFirst,
}

fn main() {
    let args = Args::parse();
    let (warm_order, crashes, zombie_window) = match args.scenario {
        Scenario::Fenced => (WarmOrder::FenceFirst, 1, 0),
        Scenario::FencedZombie => (WarmOrder::FenceFirst, 1, 1),
        Scenario::FencedReadFirst => (WarmOrder::ReadFirst, 2, 1),
    };

    let model = HandoffModel {
        pods: 2,
        routers: 2,
        late_routers: 0,
        partitions: 1,
        warm_order,
        claim_lapses: true,
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
        chunked_plans: false,
        probes: false,
    };
    println!("exploring {:?} at http://localhost:3000 …", args.scenario);
    model.checker().serve("localhost:3000");
}
