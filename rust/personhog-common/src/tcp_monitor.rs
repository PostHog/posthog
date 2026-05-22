use std::time::Duration;

const TCP_RETRANSMIT_SEGMENTS: &str = "tcp_retransmit_segments";
const TCP_SEGMENTS_OUT: &str = "tcp_segments_out";

#[cfg(target_os = "linux")]
pub fn spawn_tcp_monitor(interval: Duration) {
    tokio::spawn(async move {
        let mut tick = tokio::time::interval(interval);
        tick.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
        loop {
            tick.tick().await;
            if let Err(e) = report_tcp_stats() {
                tracing::warn!("tcp monitor stopped: {e}");
                return;
            }
        }
    });
}

#[cfg(target_os = "linux")]
fn report_tcp_stats() -> Result<(), String> {
    let contents =
        std::fs::read_to_string("/proc/net/snmp").map_err(|e| format!("read /proc/net/snmp: {e}"))?;

    let mut lines = contents.lines();
    let (headers, values) = loop {
        match lines.next() {
            Some(line) if line.starts_with("Tcp:") => {
                let header_line = line;
                let value_line = lines
                    .next()
                    .ok_or("missing Tcp values line in /proc/net/snmp")?;
                break (header_line, value_line);
            }
            Some(_) => continue,
            None => return Err("no Tcp: line found in /proc/net/snmp".to_string()),
        }
    };

    let header_fields: Vec<&str> = headers.split_whitespace().collect();
    let value_fields: Vec<&str> = values.split_whitespace().collect();

    if header_fields.len() != value_fields.len() {
        return Err("Tcp header/value field count mismatch".to_string());
    }

    for (h, v) in header_fields.iter().zip(value_fields.iter()) {
        match *h {
            "RetransSegs" => {
                if let Ok(val) = v.parse::<f64>() {
                    metrics::gauge!(TCP_RETRANSMIT_SEGMENTS).set(val);
                }
            }
            "OutSegs" => {
                if let Ok(val) = v.parse::<f64>() {
                    metrics::gauge!(TCP_SEGMENTS_OUT).set(val);
                }
            }
            _ => {}
        }
    }

    Ok(())
}

#[cfg(not(target_os = "linux"))]
pub fn spawn_tcp_monitor(_interval: Duration) {
    tracing::info!("tcp monitor: /proc/net/snmp not available on this platform, skipping");
}

#[cfg(test)]
#[cfg(target_os = "linux")]
mod tests {
    use super::*;

    #[test]
    fn report_tcp_stats_parses_successfully() {
        // On Linux CI, /proc/net/snmp should be readable
        let result = report_tcp_stats();
        assert!(result.is_ok(), "expected Ok, got: {result:?}");
    }
}
