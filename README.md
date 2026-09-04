# 🛡️ Internal Fund Integrity Monitor

### Statistical Anomaly Detection for Staff-Initiated Financial Actions

**FIM** watches refunds, discounts, voids and manual overrides tied to an employee ID and looks for statistical deviation from two reference points: that employee's own recent history, and the peer group doing the same job. Individually, each action looks like ordinary work — the pattern only becomes visible in aggregate, against the right baseline.

It is a **detection aid for human review**, not an automated accusation or disciplinary system. Every flag ships with a plain-English reason, and every scan, flag and review is written to a hash-chained, append-only audit trail.

<br>

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688?logo=fastapi&logoColor=white)
![scikit--learn](https://img.shields.io/badge/scikit--learn-1.3%2B-F7931E?logo=scikitlearn&logoColor=white)

![NumPy](https://img.shields.io/badge/NumPy-1.24%2B-013243?logo=numpy&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-hash--chained_audit_log-003B57?logo=sqlite&logoColor=white)
![pytest](https://img.shields.io/badge/tested_with-pytest-0A9EDC?logo=pytest&logoColor=white)

![Status](https://img.shields.io/badge/status-active_development-brightgreen)
![Scope](https://img.shields.io/badge/scope-defence--only-blue)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

---

## 📖 Contents

[Vision](#-vision) · [Core Design Principle](#-core-design-principle) · [Detection Pipeline](#-detection-pipeline) · [Architecture](#-architecture) · [Scoring System](#-scoring-system) · [Explainability](#-explainability) · [Dashboard](#-dashboard) · [Audit Trail and Safeguards](#-audit-trail-and-safeguards) · [Honest Metrics](#-honest-metrics) · [How It Avoids Accusing Innocent People](#-how-it-avoids-accusing-innocent-people) · [Getting Started](#-getting-started) · [Testing](#-testing) · [CLI and API](#-cli-and-api) · [Project Structure](#-project-structure) · [Development Philosophy](#-development-philosophy) · [Scope and Limitations](#-scope-and-limitations) · [License](#-license)

---

## 🎯 Vision

Small, repeated abuses of refund, discount, void and override tools are individually invisible — each one looks like a normal transaction. They only become visible in aggregate, against the right baseline. FIM builds that baseline for every employee handling money, compares live behaviour against it, and surfaces the result to a human as a **question to investigate**, not a verdict.

A published fixed rule ("refunds over £200 need a manager") is gameable the week staff learn it. A statistical baseline moves when the person moves — which is exactly the claim `scripts/evaluate.py` measures against a naive fixed-threshold rule, on the same data.

---

## 🧠 Core Design Principle

> **Every score must be explainable, and every explanation must be honest about its basis.**

Concretely, that means:

- **Robust statistics** (median / MAD) throughout, never mean and standard deviation — a single colluding employee inside a small peer group would otherwise drag the comparison towards themselves.
- **Role-aware peer comparison** — peer groups never cross roles by default, and never compare a busy employee against a quiet one on raw counts, because every feature is a rate or a shape.
- **Materiality floors** — every feature carries a minimum meaningful difference, so a tightly clustered peer group can't turn a one-point difference into a manufactured accusation.
- **Minimum z-score requirements** — a deviation is only ever reported if it clears both its materiality floor and a minimum z-score.
- **Human review, always** — a composite score that clears the flag threshold with no individually reportable reason is held at `watch`, never raised as an unexplained accusation.
- **Hash-chained audit trail** — every scan, flag and review is appended to a SHA-256 hash chain a merchant can verify independently.

---

## 🔍 Detection Pipeline

```
Events (CSV)
     │
     ▼
Feature Extraction        12 rate/shape features per employee, per rolling window
     │
     ▼
Peer / Self / Isolation Forest Scoring
     │
     ▼
Explainability             plain-English, quotable reasons ranked by contribution
     │
     ▼
Human Review                a person decides — the tool never acts on its own
     │
     ▼
Audit Trail                 hash-chained, append-only record of everything above
```

---

## 🏗️ Architecture

```
                 events.csv                     ┌──────────────────────┐
                     │                          │  Employee activity   │
                     ▼                          │  tracker (dashboard) │
  ingest ─► features ─► scoring ─► explain ─►   │  who is handling     │
             │            │          │          │  funds, and how      │
             │            │          │          └──────────┬───────────┘
    per-employee   peer z-score   plain-English            │
    rolling window self z-score   reason per flag          ▼
    baselines      isolation forest              review ─► audit trail
                                                            (hash-chained)
```

| Stage | Module(s) | Responsibility |
| --- | --- | --- |
| Ingest | `src/fim/ingest.py` | CSV → `Event`, with bad rows reported, never silently dropped |
| Features | `src/fim/features.py` | 12 behavioural rates/shapes per employee, per 7-day window vs. 28-day baseline |
| Scoring | `src/fim/scoring.py` | Robust z-scores, peer-group resolution, Isolation Forest, composite score |
| Explainability | `src/fim/explain.py` | Deviations → ranked, quotable, plain-English reasons |
| Pipeline | `src/fim/engine.py` | Orchestrates the above; the only code path that writes a flag |
| Storage | `src/fim/db.py`, `src/fim/audit.py` | SQLite schema, append-only guards, hash-chained audit log |
| API | `src/fim/api.py` | FastAPI backend serving the dashboard |
| Dashboard | `dashboard/` | Dependency-free HTML/CSS/JS tracker UI |

---

## 🧮 Scoring System

Three views of the same window are computed and kept **separate**, so a flag can always be attributed to one of them:

| Component | Basis | What it catches |
| --- | --- | --- |
| **Peer deviation** | Robust z-score (median/MAD) against colleagues in the same role, preferring the same store | The employee out of step with people doing the same job |
| **Self deviation** | Robust z-score against the employee's own four prior 7-day windows | Behaviour that changed, even if it still looks normal next to peers |
| **Isolation Forest** | Unsupervised model over the whole feature vector | Odd *combinations* no single feature makes obvious |

These three components are combined into a weighted composite (`config/config.yaml`), renormalised over whichever components are actually available, and mapped onto a **0–100 risk score**:

| Risk score | Status |
| --- | --- |
| `>= 70` | **Flagged** |
| `>= 50` | **Watch** |
| `< 50` | Clear |
| below `min_events_for_scoring` actions | **Insufficient data** — never a flag |

---

## 💬 Explainability

No flag leaves the system without a sentence a merchant could read aloud to the employee, and a number that person could challenge. Every reason states its basis — peer, self, or model — because "unusual for you" and "unusual for your role" are different claims with different remedies.

> Over the last 7 days this employee issued 70 refunds against 74 sales (94.6% of sales) versus 32.9% for peers (Returns Desk across all stores).
> *[peer basis, 37% of score, z = 10.2]*

Contributions are shares of the composite score, so a merchant can see whether a flag rests on three things or on one twitchy metric. A score that clears the flag threshold but produces no individually reportable deviation is held at `watch` rather than raised as an accusation with an empty explanation.

---

## 🖥️ Dashboard

`dashboard/` is a dependency-free page (no framework, no CDN, no build step) served directly by the FastAPI backend. It has four tabs:

| Tab | What it shows |
| --- | --- |
| **Activity Tracker** | One card per employee — live presence (`active` / `idle` / `off shift`), role, store, risk score out of 100, and the one-line reason behind it |
| **Review Queue** | Open and reviewed flags, with a form to record a human decision |
| **Audit Trail** | The hash-chained log, with chain-verification status shown inline |
| **Honest Metrics** | The latest evaluation run — precision, recall, average precision, and the naive-rule comparison |

Clicking any employee card opens a detail drawer with ranked reasons, raw feature values, score components, every flag and review, and the underlying transactions.

> 📸 *No dashboard screenshot currently exists in this repository. Add one under `dashboard/` (or an `assets/` folder) and reference it here once captured from a running instance.*

---

## 🔐 Audit Trail and Safeguards

Every scan, flag, review and decision is appended to a SQLite log (`src/fim/audit.py`, `src/fim/db.py`) where each entry commits to the **SHA-256 hash** of the entry before it:

- `verify()` walks the chain and names the first broken link.
- Database triggers reject `UPDATE` and `DELETE` on the audit log outright.
- The API exposes **no endpoint** that deletes or edits a flag — enforced by a test.

```bash
python -m fim.cli audit --verify
python -m fim.cli audit --limit 20 --payload
```

**Honest limitation:** the hash chain proves *internal consistency* of the log — it does not prove that nobody with write access to the underlying file rewrote the entire chain. To claim more, you would anchor `AuditTrail.head()` somewhere the merchant does not control (a daily email, an append-only bucket, a notary). This is a known, stated limitation, not a solved problem.

---

## 📊 Honest Metrics

```bash
python scripts/evaluate.py --trials 8
```

Measured at the thresholds actually shipped in `config/config.yaml`, over **eight independently generated synthetic stores** (32 planted actors, 192 employees):

| Metric | Precision | Recall |
| --- | --- | --- |
| Flagged | **0.82** (sd 0.14, min 0.67, max 1.00) | **0.69** (sd 0.17, min 0.50, max 1.00) |
| Flagged or watch | 0.55 | 0.75 |
| Naive rule: refund rate > 15% | 0.25 | 0.47 |

**Average precision over the ranking: 0.83.** Across the eight trials that is 22 planted actors caught, 5 false alarms, 10 missed.

**What these numbers are not:**

- Synthetic data with planted patterns this engine was designed around — an **upper bound**, not a forecast of real-world accuracy.
- 32 planted actors is a small sample; one catch or miss moves recall by a large fraction, which is why the spread is printed rather than a single figure.
- Thresholds were set by hand and were **not** tuned on held-out data.
- The `slow_burn` pattern sits near the detection limit deliberately and is caught only about half the time — catching every one of them would mean the thresholds are too loose, not that the model is good.
- **No real employee was scored** to produce any of this.

---

## 🛡️ How It Avoids Accusing Innocent People

| Failure mode | Mitigation |
| --- | --- |
| Comparing a returns clerk with a cashier | Peer groups never cross roles (`allow_cross_role_peers: false`). With no valid peer group, the peer component is dropped, not faked. |
| A tightly clustered peer group turning a 1-point difference into a 9σ accusation | Every feature carries a materiality floor that acts as a floor on sigma; a deviation below it is never reported. |
| Four historical windows producing a confident-looking six sigma | z-scores are shrunk towards zero for thin samples. |
| One colluder dragging the peer average towards themselves | Median and MAD throughout, never mean and standard deviation. |
| A new or part-time employee scored against nothing | Below `min_events_for_scoring` actions, the status is `insufficient_data` — never a flag. |
| An unexplained red dot | A flag with no reportable reason is downgraded to `watch`. |
| Quietly deleting an inconvenient flag | Append-only audit log, hash chain, no delete endpoint. |

---

## 🚀 Getting Started

### Prerequisites

- Python 3.10 or later

### Install dependencies

```bash
pip install -r requirements.txt
```

Or install the package itself (adds the `fim` console script and lets you drop `PYTHONPATH=src`):

```bash
pip install -e .
```

### Run the end-to-end demo

Generates a synthetic 24-person store with four planted bad actors, scans it, prints the tracker, runs the evaluation over eight independently generated stores, records a human review, and verifies the audit chain. Everything runs locally against `data/fim.db` — no real data is touched.

```bash
# macOS / Linux
bash scripts/demo.sh
```

```powershell
# Windows
powershell -ExecutionPolicy Bypass -File scripts\demo.ps1
```

### Start the dashboard

```bash
python -m fim.cli serve        # http://127.0.0.1:8000
```

If you have not installed the package, prefix commands with `PYTHONPATH=src`:

```bash
# macOS / Linux
export PYTHONPATH=src
```

```powershell
# Windows
$env:PYTHONPATH = "src"
```

### Configuration

All policy decisions — thresholds, scoring weights, window lengths, business hours, enabled features — live in `config/config.yaml`, so changes are visible in version control rather than buried in code. No environment variables or external database setup are required; storage is a local SQLite file at `data/fim.db`.

---

## 🧪 Testing

```bash
python -m pytest -q
```

The suite (`tests/`) covers features, scoring, explanations, audit integrity and the API — 36 tests in total:

- **`test_features.py`** — rate normalisation, recipient concentration, off-hours detection, window/baseline splitting.
- **`test_scoring.py`** — robust statistics, materiality floors, small-sample shrinkage, peer-group resolution, status thresholds, end-to-end detection on a synthetic cohort.
- **`test_explain_and_audit.py`** — every flag carries a stated, quotable reason; hash-chain integrity, tamper detection, append-only guards.
- **`test_api.py`** — overview/employee/flag endpoints, review recording, and an explicit assertion that no endpoint can delete a flag or an audit entry.

---

## 💻 CLI and API

### CLI

```bash
python -m fim.cli gen-data [--days 56] [--employees 24] [--seed 42]
python -m fim.cli scan [--as-of ISO8601] [--actor NAME]
python -m fim.cli report [--flagged-only] [--verbose]
python -m fim.cli flags [--state open|reviewed]
python -m fim.cli review --flag flag-xxx --reviewer "R. Mensah" \
                         --decision cleared --notes "Checked the receipts."
python -m fim.cli audit [--verify] [--payload] [--limit N]
python -m fim.cli evaluate
python -m fim.cli serve [--host 127.0.0.1] [--port 8000]
```

### REST API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/overview` | Scan metadata, status counts, audit chain verification |
| GET | `/api/employees` | Activity tracker feed (`?status=`, `?role=`, `?store_id=`) |
| GET | `/api/employees/{id}` | Full case: reasons, features, flags, reviews, transactions |
| GET | `/api/flags` | Flags with their reviews (`?state=open\|reviewed`) |
| POST | `/api/flags/{id}/review` | Record a human decision (reviewer, decision, notes) |
| POST | `/api/scan` | Run a scan |
| GET | `/api/audit`, `/api/audit/verify` | Audit log and chain verification |
| GET | `/api/features` | Feature catalogue with descriptions and materiality floors |
| GET | `/api/metrics` | The last evaluation run |
| GET | `/api/health` | Liveness |

Interactive docs are available at `/docs` while the server is running.

---

## 📁 Project Structure

```
config/config.yaml       thresholds, weights, windows — every policy decision, in one file
src/fim/
  ingest.py              CSV -> Event, with problems reported not swallowed
  features.py            12 features + their materiality floors and explanation templates
  scoring.py             robust z-scores, peer groups, Isolation Forest, composite
  explain.py             deviations -> ranked, quotable reasons
  engine.py              the pipeline, and the only code that writes a flag
  audit.py               hash-chained append-only log + verification
  db.py                  SQLite schema and append-only guards
  api.py                 FastAPI backend
  cli.py                 command line
dashboard/                tracker UI (no framework, no CDN, no build step)
scripts/
  generate_synthetic_data.py   labelled synthetic store with four planted patterns
  evaluate.py                  precision/recall/AP + the naive-rule baseline
  demo.ps1 / demo.sh            end-to-end demo
  run_api.ps1 / run_api.sh      start the dashboard
tests/                    36 tests: features, scoring, explanations, audit, API
```

### Bringing your own data

Point `data.events_csv` in `config/config.yaml` at a CSV with these columns:

```
event_id, timestamp, employee_id, employee_name, role, store_id, action_type,
amount, order_id, customer_ref, payment_method, original_txn_id, discount_pct, note
```

`action_type` is one of `sale`, `refund`, `discount`, `void`, `manual_override`. `sale` rows matter: they are the denominator for nearly every rate. `customer_ref` is the counterparty — the recipient-concentration features are blind without it. Timestamps are treated as naive local store time. Bad rows are reported at ingest rather than silently dropped.

---

## 🧭 Development Philosophy

- **Every flag must be explainable.** A red dot next to a person's name is an accusation; an unexplained score is treated as a bug, not a feature.
- **Policy lives in config, not code.** Thresholds and weights sit in `config/config.yaml` precisely so that changing who gets flagged is a reviewable diff.
- **Deterministic and auditable.** Scoring is deterministic given the same inputs and config, which is what makes the hash-chained audit trail worth anything.
- **Honest evaluation.** The evaluation script reports the spread across trials, not a single flattering number, and documents what the metrics are *not* as prominently as what they are.

---

## ⚠️ Scope and Limitations

FIM is a **detection aid for a human reviewer** — it is **not** an accusation engine and **not** an HR system. A high score means "these numbers are unusual and someone should look," nothing more. Statistical deviation has innocent explanations: a new returns policy, a seasonal spike, a colleague on leave, a broken terminal.

Deliberately out of scope:

- No automated discipline or automated account suspension.
- No covert surveillance of anything beyond financial actions already recorded by the point-of-sale system.
- No scoring of protected characteristics or anything derived from them.
- No keystroke, location, or personal-device data.

If you deploy this against real staff, tell them it exists and what it measures. A monitoring tool nobody has been told about fails for reasons that have nothing to do with its precision.

---

## 📄 License

`pyproject.toml` declares this project under the **MIT License**. No standalone `LICENSE` file was found in the repository at the time of writing — add one (e.g. a standard MIT template) before distributing this project.

