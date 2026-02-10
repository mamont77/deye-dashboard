# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Web dashboard for Deye solar inverters using the Solarman V5 protocol. Displays real-time solar production, battery status, grid power, home consumption, weather, and power outage schedules. Includes a Telegram bot for notifications in literary Ukrainian style.

## Development Commands

```bash
# Setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run dashboard (http://localhost:8080)
python app.py

# Run locally with Telegram disabled
./deploy_local.sh

# Deploy to remote server (interactive setup on first run)
./deploy.sh

# Test inverter connection
python test_connection.py

# Quick inverter health check
python check_inverter.py

# Diagnostic register scans
python scan_registers.py    # all registers
python scan_battery.py      # battery registers
python scan_phases.py       # phase registers
```

## Architecture

### Core Components

- **`app.py`** — Flask web server. Contains the main application, API routes, and background poller classes (`InverterPoller`, `WeatherPoller`). Serves the single-page dashboard at `/` and JSON API at `/api/*`. Manages phase stats, outage history, and grid daily logs as JSON files.

- **`inverter.py`** — `DeyeInverter` class for Modbus communication via `pysolarmanv5`. Reads holding registers with 50ms delays between reads to avoid overwhelming the logger. `BatterySampler` runs in a separate thread to smooth voltage/SOC readings using a rolling buffer with outlier rejection. `InverterConfig` dataclass describes inverter capabilities (phases, battery, PV strings).

- **`telegram_bot.py`** — Telegram bot with commands (`/battery`, `/outage`, `/grid`, `/test`). Sends notifications for low battery and grid restore events. Messages are written in 1800s literary Ukrainian style. Uses `poems.py` for weather-themed poetry excerpts.

- **`templates/index.html`** — Single-page dashboard UI with auto-refresh every 5 seconds. Contains energy flow diagrams, phase analytics, outage history, and fullscreen kiosk mode. All frontend logic is inline (no build step).

### Outage Providers

`outage_providers/` is a provider pattern for power outage schedules:
- `base.py` — `OutageProvider` base class, `OutageSchedulePoller` (background thread), and `create_outage_provider()` factory
- `lvivoblenergo.py` — Lvivoblenergo schedule provider
- `yasno.py` — Yasno (DTEK) schedule provider

### Threading Model

The app runs several daemon threads:
- `InverterPoller` — polls inverter every 60s, caches to JSON file
- `BatterySampler` — reads battery voltage/SOC every 10s for smoothing
- `WeatherPoller` — fetches Open-Meteo weather every 15 min
- `OutageSchedulePoller` — fetches outage schedule every 60s
- `TelegramBot` — runs Telegram polling loop

All pollers use thread locks for safe cache access. The inverter connection (`DeyeInverter.lock`) is shared between `InverterPoller` and `BatterySampler`.

## Inverter Connection

- Uses `pysolarmanv5` library for Modbus over TCP
- Port 8899 (Solarman V5 protocol)
- **Use holding registers** (`read_holding_registers`), not input registers
- Slave ID: 1
- Connection is opened per-poll and closed after each read cycle (see `read_all_data` → `disconnect()` in finally block)
- 50ms sleep between register reads to reduce logger connection pressure
- Configuration via environment variables: `INVERTER_IP`, `LOGGER_SERIAL`
- Inverter capabilities (phases, battery, PV strings) auto-detected at startup via `detect_config()`

## Key Registers (Holding) — 3-Phase Hybrid

| Register | Description | Scale |
|----------|-------------|-------|
| 514, 515 | PV1/PV2 Power | W |
| 586 | Battery Current (signed) | /100 A |
| 587 | Battery Voltage | /100 V |
| 588 | Battery SOC | % |
| 598 | Grid Voltage | /10 V |
| 607 | Grid Power (signed) | W |
| 644-646 | Phase Voltages L1-L3 | /10 V |
| 650-653 | Phase Loads L1-L3, Total Load | W |
| 540, 541 | DC/Heatsink Temp | (val-1000)/10 C |
| 502, 520, 521, 526 | Daily PV/Import/Export/Load | /10 kWh |

## Key Registers (Holding) — 1-Phase Hybrid (Sunsynk)

| Register | Description | Scale |
|----------|-------------|-------|
| 186, 187 | PV1/PV2 Power | W |
| 191 | Battery Current (signed, negate) | /100 A |
| 183 | Battery Voltage | /100 V |
| 184 | Battery SOC | % |
| 150 | Grid Voltage | /10 V |
| 169 | Grid Power (signed) | W |
| 176, 178 | Load L1, Total Load | W |
| 90, 91 | DC/Heatsink Temp | (val-1000)/10 C |
| 108, 76, 77, 84 | Daily PV/Import/Export/Load | /10 kWh |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/data` | GET | Current inverter readings |
| `/api/weather` | GET | Current weather and forecast |
| `/api/outage_schedule` | GET | Upcoming outage windows |
| `/api/phase-stats` | GET | Daily phase statistics |
| `/api/phase-history` | GET | Phase power history |
| `/api/outages` | GET/POST | Outage history (read/record) |
| `/api/outages/clear` | POST | Clear outage history |
| `/api/phase-stats/clear` | POST | Clear phase statistics |

## Configuration

All via environment variables (`.env` file). See `.env.example` for full template.

Required: `INVERTER_IP`, `LOGGER_SERIAL`

Optional: `WEATHER_LATITUDE/LONGITUDE`, `OUTAGE_PROVIDER` (lvivoblenergo/yasno/none), `TELEGRAM_ENABLED`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USERS`
