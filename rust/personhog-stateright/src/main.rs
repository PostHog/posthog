use stateright::Model;

use personhog_stateright::model::HandoffModel;
use personhog_stateright::types::{ModelConfig, ProtocolVariant};

fn main() {
    let protocol = std::env::args()
        .nth(1)
        .map(|s| match s.as_str() {
            "current" => ProtocolVariant::Current,
            "early-release" => ProtocolVariant::EarlyRelease,
            "stash" | "stash-and-release" | "fix" => ProtocolVariant::StashAndRelease,
            _ => {
                eprintln!("Usage: personhog-stateright [current|early-release|stash]");
                eprintln!("  current        - model current protocol (expected split-brain)");
                eprintln!("  early-release  - model early release fix");
                eprintln!("  stash          - model stash-and-release fix");
                std::process::exit(1);
            }
        })
        .unwrap_or(ProtocolVariant::Current);

    let config = ModelConfig {
        num_partitions: 4,
        num_initial_pods: 2,
        num_scaling_pods: 1,
        num_routers: 2,
        allow_crashes: false,
        protocol,
    };

    println!("=== PersonHog Handoff Protocol Model Checker ===");
    println!("Protocol:       {protocol:?}");
    println!("Partitions:     {}", config.num_partitions);
    println!("Initial pods:   {}", config.num_initial_pods);
    println!("Scaling pods:   {}", config.num_scaling_pods);
    println!("Routers:        {}", config.num_routers);
    println!("Allow crashes:  {}", config.allow_crashes);
    println!();

    let model = HandoffModel::new(config);

    // Launch the Stateright explorer web UI on port 3000
    println!("Starting Stateright explorer at http://localhost:3000");
    model.checker().serve("0.0.0.0:3000");
}
