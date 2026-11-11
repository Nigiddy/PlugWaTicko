# TicketPlug

[![Django Version](https://img.shields.io/badge/Django-3.2.16-brightgreen.svg)](https://www.djangoproject.com/)
[![DRF Version](https://img.shields.io/badge/DRF-3.13.1-red.svg)](https://www.django-rest-framework.org/)
[![Celery](https://img.shields.io/badge/Celery-5.2.7-green.svg)](https://docs.celeryq.dev/)
[![Redis](https://img.shields.io/badge/Redis-6.2%2B-red.svg)](https://redis.io/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15.2-blue.svg)](https://www.postgresql.org/)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

TicketPlug is a scalable, secure, and production-grade REST API backend for an online event ticketing and attendee management platform. Built with Python, Django, and Django REST Framework, TicketPlug provides end-to-end management for organizers, attendees, and gate attendants: from event publication and admin approval to atomic ticket reservations, Paystack payment processing, dynamic PDF ticket generation with encrypted QR tokens, and concurrency-safe gate check-in scanning.

---

## Architecture & System Overview

```
                          ┌───────────────────────┐
                          │   Client Application  │
                          │ (Web / Mobile / Gate) │
                          └──────────┬────────────┘
                                     │ HTTPS
                                     ▼
                     ┌────────────────────────────────┐
                     │     Django REST Framework      │
                     │  (Throttling / JWT Auth / FSM) │
                     └───────┬──────────────┬─────────┘
                             │              │
              ┌──────────────┴──────┐       │ Asynchronous Tasks
              ▼                     ▼       ▼
    ┌──────────────────┐    ┌─────────────────────────────────┐
    │ PostgreSQL 15.2  │    │           Celery 5.2            │
    │  - Row Locking   │    │  - PDF Ticket Generator         │
    │  - Check Constr. │    │  - Reservation Expiration Beat  │
    │  - CheckIn Logs  │    │  - Auto-Refund Handlers         │
    └──────────────────┘    └────────────────┬────────────────┘
                                             │
                                    ┌────────┴────────┐
                                    ▼                 ▼
                             ┌─────────────┐   ┌─────────────┐
                             │    Redis    │   │  Paystack   │
                             │ (Broker &   │   │  Payment    │
                             │   Cache)    │   │   Gateway   │
                             └─────────────┘   └─────────────┘
```

---

## Key Features

- **Event Lifecycle & Governance:** Event creation by organizers, complete with approval workflows managed by system administrators.
- **Inventory & Overselling Protection:** 
  - Dynamic stock calculation (`qty - sold - reserved`).
  - Row-level database locking (`select_for_update()`) during checkout.
  - 15-minute temporary reservation holds with automatic inventory release via periodic Celery Beat workers.
  - Hard database check constraints enforcing `sold <= qty` and `sold + reserved <= qty`.
- **Payment Security & Idempotency:**
  - Paystack payment gateway integration for NGN transactions.
  - Cryptographic HMAC-SHA512 webhook signature verification.
  - Idempotent webhook callbacks preventing duplicate ticket issuance.
  - Automated late-payment edge case handling (auto-refund via Paystack if stock is sold out; stock re-allocation if available).
- **Cryptographic Ticket Issuance & PDF Generation:**
  - High-entropy ticket numbers (`TKT-XXXXXXXX`) and tamper-resistant cryptographic QR tokens (`tkt_sec_...`).
  - Automated Celery workers generate branded PDF tickets with embedded base64 QR codes and email them to attendees.
- **Concurrency-Safe Gate Check-In & State Machine:**
  - Finite State Machine (FSM) statuses: `ISSUED`, `CHECKED_IN`, `CANCELLED`, `REFUNDED`, `EXPIRED`.
  - Read-only preview endpoint (`POST /api/v1/tickets/verify/`) for camera scanners.
  - Atomic gate check-in (`POST /api/v1/tickets/check-in/`) using conditional SQL updates to reject concurrent double scans (HTTP 409 Conflict).
  - Comprehensive audit trail (`CheckInLog`) tracking gate names, scanning staff, device metadata, and scan results.
- **Production Hardening:**
  - Modular settings architecture (`development.py`, `testing.py`, `production.py`).
  - Granular API rate throttling (anonymous, authenticated, auth endpoints, payments, gate scans).
  - Strict cookie security (Secure, HttpOnly, SameSite).
  - Health check endpoint (`GET /health/`) monitoring PostgreSQL and Redis connectivity.

---

## Repository Structure

```
TicketPlug/
├── ADMIN/                 # Administrative API (event approval & moderation)
├── Events/                # Event creation, ticket tier models, pricing, and reservation engine
├── Event_Project/         # Core project settings, URL routing, Celery configuration, health check
│   └── settings/          # Decomposed settings (base.py, development.py, testing.py, production.py)
├── Transactions/          # Payments, Paystack webhooks, ticket FSM models, check-in endpoints, Celery tasks
├── Users/                 # Custom user authentication (UUID PKs, JWT, dj-rest-auth)
├── templates/             # HTML templates for PDF tickets and confirmation emails
├── tests/                 # Automated test suite (inventory, check-in, webhooks, throttling)
├── docs/                  # Comprehensive architecture documents, audits, and checklists
│   ├── CODEBASE_AUDIT.md
│   ├── TECHNICAL_DESIGN_BLUEPRINT.md
│   ├── IMPLEMENTATION_CHECKLIST.md
│   ├── TESTING_REPORT.md
│   └── REMAINING_WORK.md
├── docker-compose.yml     # Multi-container orchestration (App, Celery, PostgreSQL, Redis)
├── Dockerfile             # Container definition with wkhtmltopdf system binaries
├── requirements.txt       # Python package dependencies
├── server.sh              # Container startup script (migrations, collectstatic, gunicorn)
└── worker.sh              # Celery background worker startup script
```

---

## Prerequisites

Before setting up TicketPlug, ensure your environment has:

| Component | Minimum Version | Recommended Version | Purpose |
| :--- | :--- | :--- | :--- |
| **Python** | 3.9 | **3.9.x – 3.11.x** | Core language runtime. *(Note: Python 3.13+ removes `cgi`, requiring compatibility shims with Django 3.2)* |
| **PostgreSQL** | 12.0 | **15.2+** | Relational database with row-level locking & check constraints |
| **Redis** | 5.0 | **6.2+ / 7.0+** | Message broker for Celery and caching layer |
| **wkhtmltopdf** | 0.12.5 | **0.12.6+** | System binary for PDF ticket rendering |
| **Docker & Compose** | 20.10+ | **Latest** | Optional: recommended for isolated containerized development |

---

## Quickstart: Docker Compose (Recommended)

The easiest way to run TicketPlug with all supporting services (PostgreSQL, Redis, Celery, and wkhtmltopdf) is using Docker Compose:

### 1. Clone Repository & Setup Environment
```bash
git clone https://github.com/your-org/TicketPlug.git
cd TicketPlug
cp .env.example .env
```

### 2. Configure Environment Variables
Edit `.env` and provide your secrets (see [Environment Variables](#environment-variables)):
```ini
DJANGO_ENV=development
SECRET_KEY=your-secure-random-secret-key
POSTGRES_NAME=ticketplug
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
PAYSTACK_SECRET_KEY=sk_test_your_paystack_secret_key
PAYSTACK_PUBLIC_KEY=pk_test_your_paystack_public_key
```

### 3. Build & Launch Containers
```bash
docker compose up --build
```

The application will be accessible at:
- **Swagger Interactive API:** [http://localhost:8000/](http://localhost:8000/)
- **ReDoc Documentation:** [http://localhost:8000/redoc/](http://localhost:8000/redoc/)
- **Health Check Endpoint:** [http://localhost:8000/health/](http://localhost:8000/health/)
- **Django Admin:** [http://localhost:8000/admin/](http://localhost:8000/admin/)

---

## Local Development Setup (Bare-Metal / Virtualenv)

If running without Docker, follow these steps to configure your local workstation:

### 1. Create Virtual Environment
Ensure you are using **Python 3.9, 3.10, or 3.11**:

**macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Windows (PowerShell):**
```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```
*(On modern Python 3.12+ or Windows workstations without a C compiler, install `pip install "psycopg2-binary>=2.9.9" "django-filter>=23.5" legacy-cgi`)*

### 3. Install System wkhtmltopdf
- **Ubuntu/Debian:** `sudo apt-get install -y wkhtmltopdf`
- **macOS:** `brew install wkhtmltopdf`
- **Windows:** Download and install from [wkhtmltopdf.org](https://wkhtmltopdf.org/downloads.html), and add its `bin` folder to your system `PATH`.

### 4. Configure Local Environment File
Create a `.env` file in the project root:
```ini
DJANGO_ENV=development
SECRET_KEY=local-dev-secret-key-32-chars-minimum
DEBUG=True
POSTGRES_NAME=ticketplug
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_postgres_password
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
PAYSTACK_SECRET_KEY=sk_test_your_key_here
PAYSTACK_PUBLIC_KEY=pk_test_your_key_here
```
*(Note: If `POSTGRES_NAME` is left empty in development mode, TicketPlug automatically falls back to SQLite `db.sqlite3`)*

### 5. Apply Migrations & Create Superuser
```bash
python manage.py migrate
python manage.py createsuperuser
```

### 6. Start Development Processes
Open three separate terminal sessions:

**Terminal 1 (Django API Server):**
```bash
python manage.py runserver 127.0.0.1:8000
```

**Terminal 2 (Celery Worker):**
```bash
celery -A Event_Project worker -l info
```

**Terminal 3 (Celery Beat Scheduler):**
```bash
celery -A Event_Project beat -l info
```

---

## Environment Variables

| Variable | Required | Default | Purpose |
| :--- | :--- | :--- | :--- |
| `DJANGO_ENV` | No | `development` | Environment switcher (`development`, `testing`, `production`) |
| `SECRET_KEY` | Yes | *None* | Django cryptographic signing key |
| `DEBUG` | No | `True` (dev) / `False` (prod) | Django debug mode |
| `ALLOWED_HOSTS` | No | `*` (dev) | Comma-separated list of valid Host header domains |
| `CORS_ALLOWED_ORIGINS` | No | `*` (dev) | Comma-separated list of allowed frontend origins |
| `POSTGRES_NAME` | No | `""` (dev SQLite fallback) | PostgreSQL database name |
| `POSTGRES_USER` | No | `postgres` | PostgreSQL username |
| `POSTGRES_PASSWORD` | No | `""` | PostgreSQL password |
| `POSTGRES_HOST` | No | `localhost` / `db` | PostgreSQL host address |
| `POSTGRES_PORT` | No | `5432` | PostgreSQL port |
| `CELERY_BROKER_URL` | No | `redis://127.0.0.1:6379/0` | Redis broker connection URI |
| `PAYSTACK_SECRET_KEY` | Yes | *None* | Paystack API secret key (HMAC validation & refunds) |
| `PAYSTACK_PUBLIC_KEY` | Yes | *None* | Paystack public key for client integration |
| `EMAIL_HOST_USER` | No | `""` | Gmail SMTP username for ticket delivery |
| `EMAIL_HOST_PASSWORD` | No | `""` | Gmail App Password for SMTP |
| `FRONTEND_URL` | No | `http://localhost:8000` | Base URL used to construct QR verification links |

---

## Running the Automated Test Suite

TicketPlug includes a comprehensive test suite in `tests/` and `Transactions/tests.py` verifying webhook signatures, check-in concurrency, inventory holding, and throttling.

The test configuration uses an **isolated in-memory SQLite database** and **in-memory Celery task execution**, requiring no external PostgreSQL or Redis daemons:

```bash
# Set testing environment and execute tests
# Linux / macOS:
DJANGO_ENV=testing python manage.py test tests Transactions.tests

# Windows (PowerShell):
$env:DJANGO_ENV="testing"
python manage.py test tests Transactions.tests
```

> [!NOTE]
> For details on the test architecture, concurrency guarantees, and the P0 check constraint defect notice, see [docs/TESTING_REPORT.md](file:///d:/Repos/TicketPlug/docs/TESTING_REPORT.md).

---

## Core API Endpoints

### 1. Authentication (`dj-rest-auth`)
- `POST /api/v1/signup/` - Register a new attendee or organizer account.
- `POST /api/v1/login/` - Authenticate and receive JWT session cookies.
- `POST /api/v1/logout/` - Invalidate session cookies.
- `POST /api/v1/password/reset/` - Initiate password reset email.

### 2. Events & Ticket Discovery
- `GET /api/v1/events/` - List all approved upcoming events (supports `?category=...&country=...`).
- `POST /api/v1/events/create/` - Create a new event (organizer authentication required).
- `GET /api/v1/events/<pk>/` - Retrieve event details and available ticket tiers.
- `POST /api/v1/events/tickets/create/` - Create ticket tiers and prices for an event.

### 3. Purchasing & 15-Minute Reservation
- `POST /api/v1/buy-ticket/<ticket_id>/` - Reserve tickets in cart (holds stock for 15 minutes; returns payment link).
- `POST /api/v1/remove-ticket/<pk>` - Remove item from cart and immediately restore reserved stock.
- `GET /api/v1/payment/<pk>/` - Retrieve order checkout summary and total amount.
- `POST /api/v1/payment/<pk>/` - Initiate Paystack transaction or complete free ticket checkout.

### 4. Paystack Webhook
- `POST /api/v1/paystack-webhook/` - Verified HMAC-SHA512 callback. Marks order `completed`, decrements reserved stock, increments sold stock, and dispatches Celery PDF generation.

### 5. Ticket Verification & Gate Check-In
- `POST /api/v1/tickets/verify/` - Read-only scanner preview (verifies token without mutating state).
- `POST /api/v1/tickets/check-in/` - Atomic gate check-in. Mutates state to `CHECKED_IN`, rejects duplicate scans with HTTP 409 Conflict, and records gate audit logs.
- `GET /api/v1/verify-qrcode/<event>/<key>/` - Backward-compatible endpoint for legacy QR codes.

### 6. System Health Probe
- `GET /health/` - Returns JSON status of PostgreSQL and Redis connectivity (HTTP 200 or HTTP 503).

---

## Documentation & Project Reference

For comprehensive technical deep-dives, consult the `docs/` directory:
- [docs/IMPLEMENTATION_CHECKLIST.md](file:///d:/Repos/TicketPlug/docs/IMPLEMENTATION_CHECKLIST.md): Itemized feature verification matrix and status classification.
- [docs/TESTING_REPORT.md](file:///d:/Repos/TicketPlug/docs/TESTING_REPORT.md): Testing assessment, concurrency analysis, and defect traces.
- [docs/REMAINING_WORK.md](file:///d:/Repos/TicketPlug/docs/REMAINING_WORK.md): Prioritized roadmap (P0–P3) and production launch checklist.
- [docs/TECHNICAL_DESIGN_BLUEPRINT.md](file:///d:/Repos/TicketPlug/docs/TECHNICAL_DESIGN_BLUEPRINT.md): Architectural design blueprint for the ticketing engine.
- [docs/CODEBASE_AUDIT.md](file:///d:/Repos/TicketPlug/docs/CODEBASE_AUDIT.md): Initial security and bug exploration report.

---

## License

This project is licensed under the MIT License - see the `LICENSE` file for details.
