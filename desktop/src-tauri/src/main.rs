// AttentionOS desktop pet — local-first attention observability.
// Collector thread polls the frontmost app into ~/.attentionos/attn.db
// (same schema as cli/attn.py); the pet window reads a mood computed
// from the last 30 minutes. Nothing ever leaves the machine.

#![cfg_attr(all(not(debug_assertions), target_os = "windows"), windows_subsystem = "windows")]

mod report;

use base64::Engine;
use rusqlite::Connection;
use serde::Serialize;
use std::process::Command;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    Manager,
};

const POLL_SECS: u64 = 5;
const GRACE_S: f64 = 30.0; // glance-away tolerance (METRICS.md §1)
const MIN_BLOCK_S: f64 = 60.0;

fn db_path() -> std::path::PathBuf {
    let dir = dirs::home_dir().unwrap().join(".attentionos");
    std::fs::create_dir_all(&dir).ok();
    dir.join("attn.db")
}

fn profile_path() -> std::path::PathBuf {
    dirs::home_dir().unwrap().join(".attentionos").join("profile.json")
}

pub fn open_db() -> Connection {
    let conn = Connection::open(db_path()).expect("open attn.db");
    conn.execute(
        "CREATE TABLE IF NOT EXISTS focus_events (
           source TEXT NOT NULL, start REAL NOT NULL, end REAL NOT NULL)",
        [],
    )
    .ok();
    conn
}

fn now_ts() -> f64 {
    SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs_f64()
}

fn frontmost_app() -> Option<String> {
    let out = Command::new("osascript")
        .arg("-e")
        .arg("tell application \"System Events\" to get name of first process whose frontmost is true")
        .output()
        .ok()?;
    let name = String::from_utf8_lossy(&out.stdout).trim().to_string();
    if name.is_empty() { None } else { Some(name) }
}

/// Seconds since the last keyboard/mouse input (HIDIdleTime, ns → s).
fn idle_secs() -> f64 {
    let out = match Command::new("ioreg").args(["-c", "IOHIDSystem"]).output() {
        Ok(o) => o,
        Err(_) => return 0.0,
    };
    let text = String::from_utf8_lossy(&out.stdout);
    for line in text.lines() {
        if line.contains("HIDIdleTime") {
            if let Some(v) = line.split('=').nth(1) {
                if let Ok(ns) = v.trim().parse::<f64>() {
                    return ns / 1e9;
                }
            }
        }
    }
    0.0
}

/// Collector: on focus change, close the previous event and open a new one.
const IDLE_CUTOFF_S: f64 = 120.0;

fn collector_thread() {
    let conn = open_db();
    let mut current: Option<(String, f64)> = None;
    loop {
        let now = now_ts();
        let idle = idle_secs();
        if idle > IDLE_CUTOFF_S {
            // user walked away: close the open event at the moment input stopped
            if let Some((cur, started)) = current.take() {
                let end = (now - idle).max(started);
                if end - started > 1.0 {
                    conn.execute(
                        "INSERT INTO focus_events VALUES (?1, ?2, ?3)",
                        rusqlite::params![cur, started, end],
                    )
                    .ok();
                }
            }
        } else if let Some(name) = frontmost_app().filter(|n| n != "attentionos" && n != "AttentionOS") {
            match &current {
                Some((cur, started)) if *cur != name => {
                    conn.execute(
                        "INSERT INTO focus_events VALUES (?1, ?2, ?3)",
                        rusqlite::params![cur, started, now],
                    )
                    .ok();
                    current = Some((name, now));
                }
                None => current = Some((name, now)),
                _ => {}
            }
        }
        std::thread::sleep(Duration::from_secs(POLL_SECS));
    }
}

#[derive(Serialize)]
struct PetState {
    mood: String,          // "sleeping" | "calm" | "focused" | "frazzled"
    switches_per_hr: f64,
    deep_focus_min: f64,   // today, blocks >= 10 min
    longest_block_min: f64,
    tracked_min: f64,      // last 30 min actually tracked
    current_app: String,
}

/// Merge raw events into focus blocks (simplified METRICS.md §1).
fn focus_blocks(events: &[(String, f64, f64)]) -> Vec<(f64, f64)> {
    let mut blocks: Vec<(f64, f64)> = Vec::new();
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

#[tauri::command]
fn get_state() -> PetState {
    let conn = open_db();
    let now = now_ts();
    let since_30m = now - 1800.0;
    let midnight = now - (now % 86400.0); // UTC-approx; fine for a mood

    let mut stmt = conn
        .prepare("SELECT source, start, end FROM focus_events WHERE end >= ?1 ORDER BY start")
        .unwrap();
    let day_events: Vec<(String, f64, f64)> = stmt
        .query_map([midnight], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))
        .unwrap()
        .filter_map(|r| r.ok())
        .collect();

    let recent: Vec<&(String, f64, f64)> =
        day_events.iter().filter(|(_, _, e)| *e >= since_30m).collect();
    let switches = recent.windows(2).filter(|w| w[0].0 != w[1].0).count();
    let tracked: f64 = recent
        .iter()
        .map(|(_, s, e)| (e.min(now) - s.max(since_30m)).max(0.0))
        .sum::<f64>()
        / 60.0;
    let switches_per_hr = if tracked > 1.0 { switches as f64 * 60.0 / tracked } else { 0.0 };

    let blocks = focus_blocks(&day_events);
    let deep_focus_min: f64 =
        blocks.iter().filter(|(s, e)| e - s >= 600.0).map(|(s, e)| (e - s) / 60.0).sum();
    let longest = blocks.iter().map(|(s, e)| e - s).fold(0.0, f64::max) / 60.0;

    let in_block_now = blocks.iter().any(|(_, e)| now - e < 120.0);
    let mood = if tracked < 2.0 {
        "sleeping"
    } else if switches_per_hr > 25.0 {
        "frazzled"
    } else if in_block_now && switches_per_hr < 8.0 {
        "focused"
    } else {
        "calm"
    };

    PetState {
        mood: mood.into(),
        switches_per_hr: (switches_per_hr * 10.0).round() / 10.0,
        deep_focus_min: deep_focus_min.round(),
        longest_block_min: longest.round(),
        tracked_min: tracked.round(),
        current_app: recent.last().map(|(s, _, _)| s.clone()).unwrap_or_default(),
    }
}

#[tauri::command]
fn import_profile(code: String) -> Result<serde_json::Value, String> {
    let code = code.trim();
    let payload = code.strip_prefix("attn1.").ok_or("存档码应以 attn1. 开头 / bad prefix")?;
    let bytes = base64::engine::general_purpose::URL_SAFE_NO_PAD
        .decode(payload.trim_end_matches('='))
        .map_err(|e| format!("base64: {e}"))?;
    let profile: serde_json::Value =
        serde_json::from_slice(&bytes).map_err(|e| format!("json: {e}"))?;
    if profile.get("v").and_then(|v| v.as_i64()) != Some(1) {
        return Err("未知的存档版本 / unknown profile version".into());
    }
    std::fs::write(profile_path(), serde_json::to_vec_pretty(&profile).unwrap())
        .map_err(|e| e.to_string())?;
    Ok(profile)
}

#[tauri::command]
fn get_profile() -> Option<serde_json::Value> {
    let bytes = std::fs::read(profile_path()).ok()?;
    serde_json::from_slice(&bytes).ok()
}

/// Flow mode: hide the pet entirely for `hours`, then bring it back.
/// The collector keeps running — guarding, not watching.
#[tauri::command]
fn focus_mode(app: tauri::AppHandle, hours: f64) {
    if let Some(w) = app.get_webview_window("pet") {
        w.hide().ok();
        std::thread::spawn(move || {
            std::thread::sleep(Duration::from_secs_f64(hours * 3600.0));
            w.show().ok();
        });
    }
}

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            get_state,
            import_profile,
            get_profile,
            focus_mode,
            report::get_report,
            report::annotate_gap,
            report::open_dashboard
        ])
        .setup(|app| {
            std::thread::spawn(collector_thread);

            // closing the dashboard hides it so the tray can reopen it
            if let Some(dash_win) = app.get_webview_window("dashboard") {
                let dw = dash_win.clone();
                dash_win.on_window_event(move |e| {
                    if let tauri::WindowEvent::CloseRequested { api, .. } = e {
                        api.prevent_close();
                        dw.hide().ok();
                    }
                });
            }

            let show = MenuItem::with_id(app, "show", "显示 / 隐藏宠物", true, None::<&str>)?;
            let flow = MenuItem::with_id(app, "flow", "心流模式（隐藏 2 小时）", true, None::<&str>)?;
            let dash = MenuItem::with_id(app, "dash", "今日报告", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "退出 AttentionOS", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &flow, &dash, &quit])?;
            TrayIconBuilder::new()
                .icon(tauri::image::Image::from_bytes(include_bytes!("../icons/tray.png"))?)
                .icon_as_template(true)
                .menu(&menu)
                .show_menu_on_left_click(true)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => {
                        if let Some(w) = app.get_webview_window("pet") {
                            if w.is_visible().unwrap_or(false) { w.hide().ok(); } else { w.show().ok(); }
                        }
                    }
                    "flow" => focus_mode(app.clone(), 2.0),
                    "dash" => {
                        if let Some(w) = app.get_webview_window("dashboard") {
                            w.show().ok();
                            w.set_focus().ok();
                        }
                    }
                    "quit" => app.exit(0),
                    _ => {}
                })
                .build(app)?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running AttentionOS");
}
