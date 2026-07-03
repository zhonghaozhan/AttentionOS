// AttentionOS Pro — full daily report engine (METRICS.md v0.1 ported to Rust).
// Everything is computed from the local focus_events table; gap annotations
// live in a local `annotations` table. Nothing leaves the machine.

use rusqlite::Connection;
use serde::Serialize;

const GRACE_S: f64 = 30.0;
const MIN_BLOCK_S: f64 = 60.0;
const DEEP_BLOCK_S: f64 = 300.0;
const DEEP_FOCUS_S: f64 = 600.0;
const RECOVERY_MIN: f64 = 9.5; // Mark et al., CHI 2008
const IDLE_GAP_S: f64 = 300.0;
const ANNOT_GAP_S: f64 = 900.0; // gaps >= 15 min are annotatable
const INTERRUPTERS: [&str; 8] = [
    "Slack", "Messages", "Mail", "Discord", "WeChat", "Telegram", "微信", "QQ",
];

fn day_bounds(offset_days: i64) -> (f64, f64) {
    // local midnight via chrono-free arithmetic: use `date` of now from SQLite
    // caller passes offset; we compute in seconds using localtime offset from tz
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_secs_f64();
    // approximate local midnight: shift by timezone offset read from libc
    let tz_off = tz_offset_secs();
    let local = now + tz_off;
    let midnight_local = local - (local % 86400.0);
    let start = midnight_local - tz_off - (offset_days as f64) * 86400.0;
    (start, start + 86400.0)
}

fn tz_offset_secs() -> f64 {
    // Read offset via SQLite (no extra deps): strftime('%s','now') vs localtime
    let conn = Connection::open_in_memory().unwrap();
    let off: f64 = conn
        .query_row(
            "SELECT strftime('%s','now','localtime') - strftime('%s','now')",
            [],
            |r| r.get(0),
        )
        .unwrap_or(0.0);
    off
}

fn load_events(conn: &Connection, d0: f64, d1: f64) -> Vec<(String, f64, f64)> {
    let mut stmt = conn
        .prepare("SELECT source, start, end FROM focus_events WHERE start >= ?1 AND start < ?2 AND end - start > 1 ORDER BY start")
        .unwrap();
    stmt.query_map([d0, d1], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))
        .unwrap()
        .filter_map(|r| r.ok())
        .collect()
}

fn focus_blocks(events: &[(String, f64, f64)]) -> Vec<(f64, f64)> {
    let mut blocks = Vec::new();
    let mut i = 0;
    while i < events.len() {
        let (ref anchor, start, mut end) = events[i];
        let mut j = i + 1;
        while j < events.len() {
            let (ref src, s, e) = events[j];
            if src == anchor && s - end <= GRACE_S {
                end = e;
            } else if src != anchor
                && (e - s) < GRACE_S
                && j + 1 < events.len()
                && &events[j + 1].0 == anchor
            {
                // tolerated glance
            } else {
                break;
            }
            j += 1;
        }
        if end - start >= MIN_BLOCK_S {
            blocks.push((start, end));
        }
        i = j;
    }
    blocks
}

fn median(mut v: Vec<f64>) -> f64 {
    if v.is_empty() {
        return 0.0;
    }
    v.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let n = v.len();
    (v[n / 2] + v[(n - 1) / 2]) / 2.0
}

fn deep_focus_min_for(conn: &Connection, d0: f64, d1: f64) -> f64 {
    let ev = load_events(conn, d0, d1);
    focus_blocks(&ev)
        .iter()
        .filter(|(s, e)| e - s >= DEEP_FOCUS_S)
        .map(|(s, e)| (e - s) / 60.0)
        .sum()
}

#[derive(Serialize)]
pub struct Gap {
    pub start: f64,
    pub end: f64,
    pub min: f64,
    pub hhmm: String,
    pub label: Option<String>,
}

#[derive(Serialize)]
pub struct Report {
    pub date: String,
    pub tracked_min: f64,
    pub active_hours: f64,
    pub fhl_min: f64,
    pub longest_block_min: f64,
    pub csr_per_hr: f64,
    pub recovery_min: f64,
    pub interrupt_pct: f64,
    pub self_pct: f64,
    pub deep_focus_min: f64,
    pub ab_capacity_min: f64,
    pub ab_burn: f64,
    pub recovery_debt: f64,
    pub per_source: Vec<(String, f64)>,
    pub interrupters: Vec<(String, u32)>,
    pub timeline: Vec<u8>, // 48 half-hour slots: 0 idle, 1 shallow, 2 deep
    pub gaps: Vec<Gap>,
    pub history_days: u32,
}

fn hhmm(ts: f64) -> String {
    let local = ts + tz_offset_secs();
    let secs = (local % 86400.0) as i64;
    format!("{:02}:{:02}", secs / 3600, (secs % 3600) / 60)
}

#[tauri::command]
pub fn get_report(offset_days: i64) -> Report {
    let conn = crate::open_db();
    conn.execute(
        "CREATE TABLE IF NOT EXISTS annotations (gap_start REAL PRIMARY KEY, label TEXT)",
        [],
    )
    .ok();
    let (d0, d1) = day_bounds(offset_days);
    let events = load_events(&conn, d0, d1);

    // switches & interrupts
    let switches: Vec<(&(String, f64, f64), &(String, f64, f64))> = events
        .windows(2)
        .filter(|w| w[0].0 != w[1].0)
        .map(|w| (&w[0], &w[1]))
        .collect();
    let span = events.last().map(|e| e.2).unwrap_or(d0) - events.first().map(|e| e.1).unwrap_or(d0);
    let idle: f64 = events
        .windows(2)
        .map(|w| (w[1].1 - w[0].2).max(0.0))
        .filter(|g| *g > IDLE_GAP_S)
        .sum();
    let active_hours = ((span - idle) / 3600.0).max(0.1);
    let deep_preempts = switches.iter().filter(|(p, _)| p.2 - p.1 >= DEEP_BLOCK_S).count();
    let external = switches
        .iter()
        .filter(|(_, g)| INTERRUPTERS.iter().any(|i| g.0.contains(i)))
        .count();
    let il = if switches.is_empty() { 0.0 } else { external as f64 / switches.len() as f64 };

    // blocks & budget
    let blocks = focus_blocks(&events);
    let block_mins: Vec<f64> = blocks.iter().map(|(s, e)| (e - s) / 60.0).collect();
    let fhl = median(block_mins.clone());
    let longest = block_mins.iter().cloned().fold(0.0, f64::max);
    let deep_today: f64 = blocks
        .iter()
        .filter(|(s, e)| e - s >= DEEP_FOCUS_S)
        .map(|(s, e)| (e - s) / 60.0)
        .sum();

    // capacity: p75 of past 28 days with data (excluding queried day)
    let mut history: Vec<f64> = Vec::new();
    for d in 1..=28i64 {
        let (h0, h1) = day_bounds(offset_days + d);
        let m = deep_focus_min_for(&conn, h0, h1);
        if m > 0.0 {
            history.push(m);
        }
    }
    let history_days = history.len() as u32;
    let capacity = if history.len() >= 3 {
        let mut h = history.clone();
        h.sort_by(|a, b| a.partial_cmp(b).unwrap());
        h[(h.len() * 3) / 4]
    } else {
        120.0
    };
    let burn = deep_today / capacity;

    // recovery debt: last 7 days incl. queried day
    let mut rd = 0.0;
    for d in 0..7i64 {
        let (h0, h1) = day_bounds(offset_days + d);
        let m = deep_focus_min_for(&conn, h0, h1);
        rd += (m / capacity - 1.0).max(0.0);
    }

    // per-source & interrupter counts
    let mut per: std::collections::HashMap<String, f64> = Default::default();
    for (src, s, e) in &events {
        *per.entry(src.clone()).or_default() += (e - s) / 60.0;
    }
    let mut per_source: Vec<(String, f64)> =
        per.into_iter().map(|(k, v)| (k, v.round())).collect();
    per_source.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap());
    per_source.truncate(8);

    let mut ic: std::collections::HashMap<String, u32> = Default::default();
    for (_, g) in &switches {
        if INTERRUPTERS.iter().any(|i| g.0.contains(i)) {
            *ic.entry(g.0.clone()).or_default() += 1;
        }
    }
    let mut interrupters: Vec<(String, u32)> = ic.into_iter().collect();
    interrupters.sort_by(|a, b| b.1.cmp(&a.1));

    // timeline: 48 half-hour slots
    let timeline: Vec<u8> = (0..48)
        .map(|k| {
            let a = d0 + k as f64 * 1800.0;
            let b = a + 1800.0;
            let covered: f64 = events
                .iter()
                .map(|(_, s, e)| (e.min(b) - s.max(a)).max(0.0))
                .sum();
            if covered < 1800.0 * 0.3 {
                0
            } else if blocks.iter().any(|(s, e)| *s < b && *e > a && e - s >= DEEP_FOCUS_S) {
                2
            } else {
                1
            }
        })
        .collect();

    // annotatable gaps (>= 15 min between events)
    let mut gaps = Vec::new();
    for w in events.windows(2) {
        let g = w[1].1 - w[0].2;
        if g >= ANNOT_GAP_S {
            let label: Option<String> = conn
                .query_row(
                    "SELECT label FROM annotations WHERE gap_start = ?1",
                    [w[0].2],
                    |r| r.get(0),
                )
                .ok();
            gaps.push(Gap {
                start: w[0].2,
                end: w[1].1,
                min: (g / 60.0).round(),
                hhmm: format!("{}–{}", hhmm(w[0].2), hhmm(w[1].1)),
                label,
            });
        }
    }

    Report {
        date: {
            let local = d0 + tz_offset_secs();
            let days = (local / 86400.0) as i64;
            // civil date from days since epoch (Howard Hinnant's algorithm)
            let (y, m, d) = civil_from_days(days);
            format!("{y:04}-{m:02}-{d:02}")
        },
        tracked_min: ((span - idle) / 60.0).round(),
        active_hours: (active_hours * 10.0).round() / 10.0,
        fhl_min: (fhl * 10.0).round() / 10.0,
        longest_block_min: longest.round(),
        csr_per_hr: ((switches.len() as f64 / active_hours) * 10.0).round() / 10.0,
        recovery_min: (deep_preempts as f64 * RECOVERY_MIN).round(),
        interrupt_pct: (il * 100.0).round(),
        self_pct: 100.0 - (il * 100.0).round(),
        deep_focus_min: deep_today.round(),
        ab_capacity_min: capacity.round(),
        ab_burn: (burn * 100.0).round() / 100.0,
        recovery_debt: (rd * 100.0).round() / 100.0,
        per_source,
        interrupters,
        timeline,
        gaps,
        history_days,
    }
}

fn civil_from_days(z: i64) -> (i64, u32, u32) {
    let z = z + 719468;
    let era = if z >= 0 { z } else { z - 146096 } / 146097;
    let doe = (z - era * 146097) as u64;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = yoe as i64 + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    (if m <= 2 { y + 1 } else { y }, m, d)
}

#[tauri::command]
pub fn annotate_gap(gap_start: f64, label: String) -> Result<(), String> {
    let conn = crate::open_db();
    conn.execute(
        "CREATE TABLE IF NOT EXISTS annotations (gap_start REAL PRIMARY KEY, label TEXT)",
        [],
    )
    .ok();
    conn.execute(
        "INSERT INTO annotations (gap_start, label) VALUES (?1, ?2)
         ON CONFLICT(gap_start) DO UPDATE SET label = ?2",
        rusqlite::params![gap_start, label],
    )
    .map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
pub fn open_dashboard(app: tauri::AppHandle) {
    use tauri::Manager;
    if let Some(w) = app.get_webview_window("dashboard") {
        w.show().ok();
        w.set_focus().ok();
    }
}
