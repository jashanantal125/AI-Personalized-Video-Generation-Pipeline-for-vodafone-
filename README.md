## Vodafone Idea (Vi) Campaign Automation & Personalized Video Platform

### Overview

This project is an **automation and data processing platform** built for **Vodafone Idea (Vi)** to manage large-scale marketing campaigns and personalized video offers.


It ingests encrypted telecom data from Vi servers, applies **advanced validation and deduplication logic**, stores cleaned data in a **MySQL analytics schema**, and then drives a **multi-language personalized video generation pipeline** using **Google Cloud Text-to-Speech (TTS)**.

The system is designed with strong themes around **Advanced Analytics, Data Science, and Computer Engineering**, and can support use cases aligned with:

- **Dispute Advisory** – reproducible logs and audit trails for what data was ingested, transformed, or excluded.
- **Risk & Investigations** – robust duplicate detection and validation rules to reduce data quality risk.
- **Regulatory and Litigation Support** – traceable processing steps, configurable controls, and structured storage of sensitive customer-related data.

<img width="906" height="773" alt="Screenshot 2026-03-13 at 6 33 39 PM" src="https://github.com/user-attachments/assets/363d56fc-0f65-40ae-9873-a427c9bf0ea1" />

---
This repository is published as a sanitized showcase: it highlights architecture and implementation patterns while intentionally excluding sensitive configurations and any real client data.
## Core Features

### 1. High-Volume CSV Ingestion & Cleaning

- **Encrypted mobile number ingestion** from Vi server CSV files (e.g. `BOAT_*.csv`).
- **Decryption via MySQL functions** with configurable keys.
- **Data validation and cleaning**:
  - Validation of fields like `circle_name`, `validity`, and `current_balance`.
  - Graceful handling of invalid / missing / noisy values.
- **Idempotent campaign creation**:
  - Skip already processed campaigns based on `campaign_name`.
  - Maintain counts such as `total_users`, `duplicate_num_per_day`, and error stats.

### 2. Daily Duplicate Detection & Risk Control

- **Daily per-mobile duplicate control** using a structured CSV log:
  - Ensures the same mobile number is not targeted multiple times per day (except for whitelisted numbers).
  - Captures metadata such as first occurrence timestamp and last associated campaign.
- Supports **Risk & Investigations** scenarios by:
  - Keeping a clear record of when numbers were first used.
  - Providing statistics on duplicates and invalid rows.

### 3. Personalized Video Offer Generation

- Uses **Google Cloud Text-to-Speech** to render offer details (validity, amount, language) into audio.
- **Template-driven video configuration** via `video_config.json`:
  - Per-circle / per-language base video (e.g. Hindi, Tamil, Telugu, Gujarati, Kannada, Bengali, Marathi).
  - Timecodes for when to overlay **validity** and **amount** text.
  - Screen coordinates for text overlays at different speaking rates.
- Generates rich, **personalized promotional videos** for Vi subscribers and syncs them to a **public web endpoint**.

### 4. Automation & Operational Monitoring

- **Worker scripts** (`start_workers.sh`, `stop_workers.sh`, `status_workers.sh`) to control multiple long-running processes.
- Shell scripts for:
  - **Realtime video sync** to the web server (`realtime_video_sync*.sh`).
  - **Secure SFTP/FTP transfers** of CSVs and generated videos.
- Detailed **logging** (`vi_server_data_YYYYMMDD.log`) for:
  - Per-row processing outcomes.
  - Database errors and retries.
  - Aggregated processing summaries.

---

## Architecture

### High-Level Components

- **VodafoneIdea-automation/**
  - Production-oriented automation for:
    - CSV ingestion (`script_1_automated.py`, `script_2.py`, `script_3.py`).
    - Monitoring and worker orchestration.
    - Video configuration via `video_config.json`.
- **VodafoneIdea-multiinstance/**
  - Multi-instance / testing variations of the automation:
    - Test ingestion pipelines (e.g. `script_1_automated.py`, `script_2.py`, `script_3_bulk_api.py`).
    - Separate configurations and backup scripts.
- **Database Layer**
  - MySQL with tables such as `campaigns`, `users`, `test_campaigns`, `test_users`.
  - `db_script.py` encapsulates connection details.
- **Video & TTS Layer**
  - Google Cloud TTS via `google-cloud-texttospeech`.
  - Video templates and overlay coordinates defined per circle/language.

### Data Flow

1. **Input**
   - Encrypted CSVs from Vi server land in `vi_server_files/`.
   - Each file name encodes a campaign (e.g. `BOAT_YYYY_MM_DD_hh_mm_ss.csv`).

2. **Ingestion & Transformation**
   - Python scripts:
     - Read CSV.
     - Detect delimiter.
     - Normalize headers.
     - Decrypt mobile numbers using a SQL function.
     - Validate and clean numeric fields (e.g. `ul_validity_diff`, `current_balance`).
     - Validate `circle_name` and enforce integer encoding.

3. **Duplicate Control & Storage**
   - Check per-day duplicate usage in an **`input_numbers/YYYY-MM-DD.csv`** registry.
   - Insert valid users into `campaigns` / `users` or `test_campaigns` / `test_users`.
   - Maintain counts for total rows, inserted rows, duplicates, invalids, and errors.

4. **Personalized Video Generation**
   - For selected circles:
     - Load template parameters from `video_config.json`.
     - Generate a TTS voiceover for the offer in the appropriate language.
     - Overlay text (validity, amount) at configured coordinates and timestamps.
     - Export final videos to `output_videos_vi/`.

5. **Distribution & Monitoring**
   - Sync generated videos to a web-accessible directory (e.g. `/var/www/html/vid`).
   - Compose public URLs based on `public_url_base`.
   - Monitor logs and worker processes using helper scripts and cron jobs.

---

## Example Code Snippets

### 1. Secure CSV Ingestion & Campaign Creation

```python
from db_script import db_connection

def ingest_campaign(csv_file_path: str):
    conn = db_connection()
    cursor = conn.cursor()

    # Derive campaign name from file name (e.g. BOAT_2025_10_03_18_00_45.csv)
    campaign_name = extract_campaign_name_from_filename(csv_file_path)

    # Skip if campaign already processed
    campaign_id = campaign_exists(campaign_name)
    if campaign_id:
        logger.info(f"Campaign '{campaign_name}' already exists (ID: {campaign_id}), skipping.")
        return

    # Create new campaign record
    campaign_id = create_campaign(campaign_name)

    # Stream CSV rows, decrypt mobile, validate fields, and insert users
    for row in read_vi_csv(csv_file_path):
        encrypted_mobile = clean_mobile_hex(row["mobile_no"])
        circle_name = validate_circle_name(row["circle_name"])
        validity_diff = safe_convert_to_int(row["ul_validity_diff"], "ul_validity_diff")
        current_balance = safe_convert_to_decimal(row["current_balance"], "current_balance")

        if not encrypted_mobile or circle_name is None:
            continue

        insert_user(campaign_id, encrypted_mobile, circle_name, validity_diff, current_balance)

    conn.commit()
```

### 2. Daily Duplicate Detection for Risk & Investigations

```python
def check_and_update_daily_mobile(decrypted_mobile: str, campaign_id: int) -> bool:
    # Whitelisted numbers can be added multiple times per day
    if decrypted_mobile in ALLOWED_DUPLICATE_NUMBERS:
        return True

    if decrypted_mobile in daily_mobiles_data:
        # Already targeted today → treat as duplicate
        entry = daily_mobiles_data[decrypted_mobile]
        entry["occurrence_count"] += 1
        entry["last_campaign_id"] = campaign_id
        logger.debug(f"Duplicate mobile detected: {decrypted_mobile}")
        return False

    # First time today → create a new entry
    daily_mobiles_data[decrypted_mobile] = {
        "first_occurence_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "occurrence_count": 1,
        "last_campaign_id": campaign_id,
    }
    return True
```

### 3. Video Template Selection for Personalized Offers

```python
import json

with open("video_config.json", "r") as f:
    config = json.load(f)

video_configs = config["video_configs"]
default_config = config.get("default_config", {})

def select_video_template(circle_code: str):
    """
    Given a circle code (e.g. "6" or "21"), return
    the appropriate base video and TTS configuration.
    """
    template = video_configs.get(circle_code) or video_configs[default_config.get("circle", "6")]

    return {
        "input_video_path": template["input_video_path"],
        "language_code": template["language_code"],
        "tts_voice_name": template["tts_voice_name"],
        "validity_start_time": template["validity_start_time"],
        "amount_start_time": template["amount_start_time"],
        "coordinates": template["coordinates_map"],
        "public_url_base": default_config.get("public_url_base"),
    }
```

---

## Alignment with Advanced Analytics, Data Science & Forensic Consulting

- **Advanced Analytics / Data Science**
  - Cleans and structures high-volume transactional data for downstream analysis.
  - Tracks metrics like valid vs invalid rows, duplicates, and campaign-level performance attributes.
- **Computer Engineering**
  - Production-grade automation with worker scripts, logging, error handling, and multi-instance support.
  - Integration with cloud services (Google Cloud TTS) and external SFTP/FTP endpoints.
- **Dispute Advisory & Regulatory / Litigation Support**
  - Deterministic, logged processing pipeline that can reconstruct:
    - Which records were accepted or rejected.
    - Why specific records were dropped (invalid circle, empty mobile, etc.).
  - Campaign and user-level statistics to support forensic analysis.
- **Risk & Investigations**
  - Strict duplicate controls and validation rules reduce the risk of mis-targeting subscribers.
  - Detailed logs enable back-tracing data issues and irregularities.

---

## Tech Stack

- **Language**: Python 3
- **Data & DB**: MySQL (`mysql.connector`, `PyMySQL`)
- **Cloud Services**: Google Cloud Text-to-Speech (`google-cloud-texttospeech`)
- **Automation / Ops**: Bash scripts (`start_workers.sh`, `status_workers.sh`, SFTP/FTP sync scripts)
- **Logging & Monitoring**: Python `logging` module with daily log files
- **Config**: JSON configs for video templates and environment paths

---

## Project Structure (High Level)

- `VodafoneIdea-automation/`
  - Core ingestion scripts and production worker setup.
  - `video_config.json` – video and TTS configurations.
- `VodafoneIdea-multiinstance/`
  - Multi-instance / experimental ingestion and bulk API scripts.
  - Alternate `video_config.json`.
- `input_numbers/`
  - Daily CSVs used for duplicate detection and auditing.
- `vi_server_files/`
  - Landing zone for incoming Vi CSVs.
- `output_videos_vi/` (configured path)
  - Generated personalized offer videos ready for distribution.
