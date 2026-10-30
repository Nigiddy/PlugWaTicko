# TicketPlug — Comprehensive Codebase Audit


---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Technology Stack](#2-technology-stack)
3. [Project Architecture](#3-project-architecture)
4. [Repository Structure](#4-repository-structure)
5. [Implemented Features](#5-implemented-features)
6. [Database Architecture](#6-database-architecture)
7. [Local Development Setup Guide](#7-local-development-setup-guide)
8. [Environment Variables and External Integrations](#8-environment-variables-and-external-integrations)
9. [Recommended Development Roadmap](#9-recommended-development-roadmap)

---

## 1. Executive Summary

TicketPlug is a **Django REST Framework** backend for an online event ticketing platform. It was built as a solo open-source project and provides a fully functional API for the complete ticket commerce lifecycle: organizers create events, administrators approve them, customers browse events and purchase tickets via Paystack, and the system automatically generates PDF tickets embedded with unique QR codes that are emailed to attendees and can be scanned for entry validation.

The project is containerised with Docker Compose and is designed to be deployed behind Gunicorn with a PostgreSQL database and Redis-backed Celery worker. The API is documented with both Swagger UI (drf-yasg) and ReDoc.

**Maturity level:** The core ticketing flow is functional end-to-end. Several advanced subsystems (wallet/payout, event search, category slugs) are partially stubbed or contain minor bugs that need to be addressed before production use.

---

## 2. Technology Stack

| Layer | Technology | Version pinned | Purpose |
|---|---|---|---|
| **Language** | Python | 3.9 (Dockerfile) | Runtime |
| **Web framework** | Django | 3.2.16 | MVC foundation, ORM, admin panel |
| **REST API** | Django REST Framework (DRF) | 3.13.1 | Serializers, generic views, permissions |
| **Authentication** | dj-rest-auth + django-allauth | 3.0.0 / 0.51.0 | Registration, login, email verification, password reset |
| **JWT tokens** | djangorestframework-simplejwt | 5.2.0 | Stateless API authentication via HTTP-only cookies |
| **Database** | PostgreSQL | 15.2 (Docker image) | Primary relational store |
| **ORM** | Django ORM + `django.contrib.postgres` | — | Database access layer |
| **DB adapter** | psycopg2-binary | 2.9.3 | Python ↔ PostgreSQL driver |
| **Task queue** | Celery | 5.2.7 | Async background jobs (ticket generation, email dispatch) |
| **Message broker** | Redis | alpine (Docker image) | Celery broker & result backend |
| **Redis Python client** | redis + django-redis | latest | Python interface to Redis |
| **Payment gateway** | Paystack | via REST API | Online card payments (Nigerian-centric) |
| **Image hosting** | Cloudinary | latest SDK | Stores event banner images in the cloud |
| **PDF generation** | pdfkit | latest | Converts HTML ticket templates to PDF bytes |
| **QR codes** | qrcode + Pillow | latest / 9.2.0 | Generates base-64 encoded PNG QR codes |
| **Email** | Django SMTP (Gmail) | — | Delivers ticket PDFs and verification emails |
| **CORS** | django-cors-headers | 3.13.0 | Allows cross-origin requests from a frontend |
| **Filtering** | django-filter | 22.1 | URL-param-based QuerySet filtering |
| **API docs** | drf-yasg + django-rest-swagger | 1.21.3 / 2.2.0 | Swagger UI & ReDoc auto-documentation |
| **Config management** | python-decouple | 3.6 | Reads settings from `.env` file |
| **Static files** | Whitenoise | 6.2.0 | Serves static assets in production without a separate web server |
| **Production WSGI** | Gunicorn | 20.1.0 | Production-grade WSGI server |
| **Containerisation** | Docker + Docker Compose | — | Reproducible dev/prod environment |
| **Timezone data** | pytz + tzdata | 2022.1 | Timezone-aware datetime handling |

### Why each key technology was chosen

- **Django / DRF** — Django's batteries-included approach (admin panel, ORM, migrations, auth) accelerated development. DRF adds the serializer/viewset layer needed for a REST API.
- **Celery + Redis** — Ticket PDF generation and email sending are computationally slow and must not block the HTTP response. Celery dispatches these as async tasks via the Redis broker.
- **Paystack** — A payment gateway popular in West Africa that supports NGN payments; chosen to match the project's Nigerian timezone (`Africa/Lagos`) and market.
- **Cloudinary** — A managed image CDN that handles uploads, transformations, and serving of event banner images, removing the need for local media storage in a stateless container.
- **pdfkit** — Wraps `wkhtmltopdf` to convert Django HTML templates into PDF bytes, enabling the styled ticket PDFs.
- **dj-rest-auth + django-allauth** — Provides a complete authentication suite (registration, email verification, password reset) with minimal custom code.
- **JWT (HttpOnly cookies)** — Tokens are stored in `HttpOnly` cookies (`ticket-plug-access-cookie` / `ticket-plug-refresh-cookie`) to prevent XSS-based token theft.

---

## 3. Project Architecture

TicketPlug follows Django's canonical **app-per-domain** monolith pattern. There is no service-level decomposition; all logic lives in a single Django process except for background tasks, which run in a separate Celery worker process.

```
                        ┌─────────────────────────────┐
                        │      HTTP Client / Frontend  │
                        └────────────┬────────────────┘
                                     │ HTTPS
                        ┌────────────▼────────────────┐
                        │     Gunicorn (WSGI server)   │
                        │         Port 8000            │
                        └────────────┬────────────────┘
                                     │
                        ┌────────────▼────────────────┐
                        │       Django Application     │
                        │  ┌───────┐  ┌────────────┐  │
                        │  │Users  │  │  Events    │  │
                        │  └───────┘  └────────────┘  │
                        │  ┌──────────────┐  ┌──────┐ │
                        │  │ Transactions │  │ADMIN │ │
                        │  └──────────────┘  └──────┘ │
                        └──┬──────────────────┬───────┘
                           │                  │
              ┌────────────▼──┐     ┌─────────▼──────┐
              │  PostgreSQL   │     │    Redis        │
              │  (primary DB) │     │ (Celery broker) │
              └───────────────┘     └────────┬───────┘
                                             │
                                   ┌─────────▼──────┐
                                   │  Celery Worker  │
                                   │ (ticket+email)  │
                                   └────────┬───────┘
                                            │
                                   ┌────────▼──────────────┐
                                   │ External services:     │
                                   │  • Gmail SMTP          │
                                   │  • Cloudinary CDN      │
                                   │  • Paystack API        │
                                   └───────────────────────┘
```

### Request / Payment flow

```
User selects ticket      → POST /api/v1/buy-ticket/<ticket_id>/
  → BuyTicket + OrderTicket created (status: not completed)
  → Response: { payment_link, amount_to_pay }

User initiates payment   → POST /api/v1/make-payment/<order_id>/
  → If free: create_payment_record.delay() immediately
  → If paid: call Paystack /transaction/initialize → return payment URL to user

Paystack redirects user + fires webhook → POST /api/v1/paystack-webhook/
  → charge.success → create_payment_record.delay()
  → charge.failed  → payment_failed.delay()

Celery worker (create_payment_record):
  → Creates Payment record
  → Marks OrderTicket status = 'completed'
  → Increments TicketPrice.sold counter
  → For each ticket: generates key, generates QR code, renders PDF, sends email
```

---

## 4. Repository Structure

```
TicketPlug/
│
├── manage.py                  # Django CLI entry point
├── requirements.txt           # Python dependencies (pip)
├── Dockerfile                 # Python 3.9-slim container image
├── docker-compose.yml         # Orchestrates: app, celery worker, postgres, redis
├── server.sh                  # Docker entrypoint: migrate → createsuperuser → collectstatic → gunicorn
├── worker.sh                  # Docker entrypoint for Celery: celery -A Event_Project worker
├── .gitignore                 # Excludes .env, __pycache__, static/, venv/, db.sqlite3
├── README.md                  # Brief project overview and Docker quickstart
├── CODEBASE_AUDIT.md          # (Root-level copy — canonical copy is docs/CODEBASE_AUDIT.md)
│
├── Event_Project/             # Django project package (settings, root URLs, Celery config)
│   ├── __init__.py            # Imports celery_app so it auto-loads with Django
│   ├── settings.py            # All configuration (reads from .env via python-decouple)
│   ├── urls.py                # Root URL router — includes all app url modules + Swagger
│   ├── celery.py              # Celery application definition; autodiscovers tasks
│   ├── adapter.py             # CustomAdapter overrides allauth's email confirmation URL
│   │                          #   to point to FRONTEND_URL for SPA email verification
│   ├── asgi.py                # ASGI entry point (not actively used; no WebSocket support)
│   └── wsgi.py                # WSGI entry point for Gunicorn
│
├── Users/                     # Custom user model + organiser/buyer profile endpoints
│   ├── models.py              # User (AbstractBaseUser, UUID PK, email auth)
│   │                          #   + helper methods: get_total_amount_earned,
│   │                          #     get_total_tickets_sold, get_total_event_created
│   ├── serializers.py         # RegisterSerializer, LoginSerializer, UserDetailSerializer,
│   │                          #   UserDashboardSerializer, UserEventSerializer,
│   │                          #   UserBoughtTicketsHistory, UserPaymentHistory,
│   │                          #   PasswordReset (custom validation)
│   ├── views.py               # PaymentHistoryView, MyboughtTickets, ListUnApprovedEvents,
│   │                          #   UpdateEventstatus (duplicate of ADMIN), UserDashBoard,
│   │                          #   UserCreatedEvents, PasswordResetview
│   ├── urls.py                # payment-history/, my-bought-tickets/, unapproved-events/,
│   │                          #   dashboard/, my-events/, password-reset/
│   ├── admin.py               # Registers User in Django Admin
│   └── migrations/
│       └── 0001_initial.py    # Creates the custom User table
│
├── Events/                    # Core event & ticket-cart domain
│   ├── models.py              # Category, Event, TicketPrice, BuyTicket, OrderTicket,
│   │                          #   TrendingEvents
│   ├── serializers.py         # EventSerializer, EventCreateSerializer,
│   │                          #   CreateEventPriceSerializer, BuyTicketSerializer,
│   │                          #   CategorySerializer, TrendingEventSerializer
│   ├── views.py               # EventView (list approved), EventCreateView,
│   │                          #   EventDetailView (RUD), CreateEventTicketPrice,
│   │                          #   BuyTicketView (add-to-cart), RemoveTicketView,
│   │                          #   CategoryView, TrendingEventss, TrendingEventView
│   ├── permissions.py         # IsAdmin, IsAdminorReadOnly, IsOwner
│   ├── urls.py                # events/, create/event/, events/<uuid>/, buy-ticket/<id>/,
│   │                          #   create/event-ticket/, categories/,
│   │                          #   trending-events/, update-trending-events/
│   ├── admin.py               # EventAdmin (with TicketPrice inline), Event_FeeAdmin,
│   │                          #   Category, TrendingEvents, BuyTicket, OrderTicket
│   └── migrations/
│       ├── 0001_initial.py    # Creates: BuyTicket, Category, Event, TrendingEvents,
│       │                      #   TicketPrice, OrderTicket (without FK to User)
│       └── 0002_initial.py    # Adds FK relationships to User (swappable dependency)
│
├── Transactions/              # Payment processing, Celery tasks, ticket generation
│   ├── models.py              # Payment (UUID PK, Paystack ref, amount, OneToOne → OrderTicket)
│   │                          #   SoldTicket (UUID PK, key, used flag, FK to Payment/TicketPrice)
│   ├── serializers.py         # PaymentSErializer (email field), CheckoutSerializer
│   ├── views.py               # Makepayment (GET checkout / POST initiate Paystack),
│   │                          #   PayStack_Webhook (receives Paystack events),
│   │                          #   VerifyQrcode (validate ticket by key+event_id)
│   ├── tasks.py               # generate_ref_code(), generate_key(), generate_pdf(),
│   │                          #   generate_qrcode(), create_ticket() (heavy lifting),
│   │                          #   @shared_task create_payment_record(),
│   │                          #   @shared_task payment_failed()
│   ├── utils.py               # format_date() — formats event date range as human string
│   ├── urls.py                # make-payment/<uuid>/, paystack-webhook/, verify-qrcode/<uuid>/<int>/
│   ├── admin.py               # SoldTicketAdmin, PaymentAdmin
│   └── migrations/
│       ├── 0001_initial.py    # Creates Payment and SoldTicket (without User FK)
│       └── 0002_initial.py    # Adds User FK to Payment and SoldTicket
│
├── ADMIN/                     # Thin admin-only API app (approve events via API)
│   ├── models.py              # Empty — no additional models
│   ├── serializers.py         # ApproveEventSerializer (wraps Event.approved field)
│   ├── views.py               # UpdateEventstatus (PATCH /api/v1/admin/approve-event/<uuid>/)
│   ├── urls.py                # approve-event/<uuid>/
│   └── migrations/
│       └── __init__.py        # No migrations (no models)
│
└── templates/                 # Django HTML templates (for email and PDF rendering)
    ├── base.html              # Base email HTML template with a message block
    ├── ticket.html            # HTML email body sent to ticket purchaser
    └── pdf.html               # Ticket PDF template — renders ticket card(s) with QR code
                               #   Supports both single-ticket and multi-ticket (loop) modes
```

### Notable architectural observations

- **`ADMIN` vs `Users` duplication** — `UpdateEventstatus` (approve event) is implemented in _both_ `ADMIN/views.py` and `Users/views.py`. The ADMIN app's version is the authoritative one served at `api/v1/admin/approve-event/<uuid>/`.
- **No `apps.py` label mismatch** — The directory is named `ADMIN` (uppercase) but `apps.py` declares `name = 'Admin'` (title-case). Django resolves this correctly, but it is a potential source of confusion.
- **`Event_Project/__init__.py`** explicitly imports the Celery app so that Django's `AppRegistry` initialises Celery when the server starts — this is the standard Django + Celery bootstrap pattern.
- **Tags stored as stringified Python list** — `Event.tags` is a `CharField` storing `repr(list)`, deserialized with `eval()` in the serializer. This is a tech-debt item (should use `ArrayField` from `django.contrib.postgres`).

---

## 5. Implemented Features

### Legend
| Symbol | Status |
|---|---|
| ✅ | Fully implemented |
| ⚠️ | Partially implemented / has known bugs |
| 🔲 | Stubbed / commented out |
| ❌ | Not implemented |

---

### 5.1 User Registration and Authentication

| Feature | Status | Location |
|---|---|---|
| Register with email + first/last name + password | ✅ | `POST /api/v1/signup/` → `dj_rest_auth.registration` + `Users.serializers.RegisterSerializer` |
| Email verification (mandatory, via allauth) | ✅ | `settings.py: ACCOUNT_EMAIL_VERIFICATION='mandatory'`; `adapter.py` redirects confirmation link to `FRONTEND_URL` |
| Login with email + password, returns JWT cookies | ✅ | `POST /api/v1/login/` → `dj_rest_auth` + `Users.serializers.LoginSerializer` |
| JWT via HttpOnly cookies (access + refresh) | ✅ | `settings.py: REST_AUTH USE_JWT=True`; cookies named `ticket-plug-access-cookie` / `ticket-plug-refresh-cookie` |
| Access token lifetime: 6 minutes | ✅ | `settings.py: SIMPLE_JWT ACCESS_TOKEN_LIFETIME=timedelta(minutes=6)` |
| Refresh token lifetime: 14 days | ✅ | `settings.py: SIMPLE_JWT REFRESH_TOKEN_LIFETIME=timedelta(days=14)` |
| Logout | ✅ | `POST /api/v1/logout/` → `dj_rest_auth` |
| Password reset via email | ✅ | `POST /api/v1/password-reset/` → `Users.views.PasswordResetview` (custom email validation) |
| Password reset confirm | ✅ | `POST /api/v1/password/reset/confirm/<uidb64>/<token>/` → `dj_rest_auth.PasswordResetConfirmView` |
| Password change (authenticated) | ✅ | `POST /api/v1/password/change/` → `dj_rest_auth` (`OLD_PASSWORD_FIELD_ENABLED=True`) |
| Social / OAuth login | ❌ | allauth installed but no social providers configured |
| Username-based login | ❌ | Intentionally disabled (`ACCOUNT_USERNAME_REQUIRED=False`) |

---

### 5.2 User Profiles and Account Management

| Feature | Status | Location |
|---|---|---|
| View own profile (id, email, name, is_superuser, is_staff, email_confirmed) | ✅ | `GET /api/v1/user/` → `dj_rest_auth` + `Users.serializers.UserDetailSerializer` |
| Edit profile (first_name, last_name, etc.) | ❌ | No PATCH/PUT endpoint for profile fields |
| Organiser dashboard (total earned, tickets sold, events created) | ✅ | `GET /api/v1/dashboard/` → `Users.views.UserDashBoard` |
| Payment history (list of payments made by current user) | ✅ | `GET /api/v1/payment-history/` → `Users.views.PaymentHistoryView` |
| My bought tickets (list of completed orders + ticket details) | ✅ | `GET /api/v1/my-bought-tickets/` → `Users.views.MyboughtTickets` |
| My created events (list of organiser's events + ticket stats) | ✅ | `GET /api/v1/my-events/` → `Users.views.UserCreatedEvents` |
| Wallet / withdrawal system | 🔲 | Commented out in `Users.models` (`get_total_withdrawn_amount`, `get_wallet_balance`) and `Users.views` (`UserWalletBalanceView`) |

---

### 5.3 Roles and Permissions

| Feature | Status | Location |
|---|---|---|
| `is_superuser` / `is_staff` flags on User model | ✅ | `Users.models.User`; `create_superuser` sets both |
| `IsAdmin` permission — blocks non-staff users | ✅ | `Events.permissions.IsAdmin` (checks `is_superuser or is_staff`) |
| `IsAdminorReadOnly` — read-only for everyone, write for staff | ✅ | `Events.permissions.IsAdminorReadOnly`; used on `CategoryView` |
| `IsOwner` — object-level; write only for the event creator | ✅ | `Events.permissions.IsOwner`; used on `EventDetailView` |
| Role-based access on approve-event endpoints | ✅ | Both `ADMIN/views.py` and `Users/views.py` use `IsAdmin` |
| Fine-grained role system (organiser, attendee, staff tiers) | ❌ | All roles expressed solely through `is_staff`/`is_superuser` boolean flags |

---

### 5.4 Event Creation and Management

| Feature | Status | Location |
|---|---|---|
| Create an event (name, location, description, image, dates, categories, tags) | ✅ | `POST /api/v1/create/event/` → `Events.views.EventCreateView` |
| Event image uploaded to Cloudinary | ✅ | `Event.image = CloudinaryField(...)` |
| List all approved, future events | ✅ | `GET /api/v1/events/` → `Events.views.EventView` (filters `approved=True, end_date > now`) |
| Filter events by `category` or `country` | ✅ | `DjangoFilterBackend` on `EventView`; `filterset_fields=['category','country']` |
| Retrieve / Update / Delete a single event (owner only) | ✅ | `GET/PATCH/DELETE /api/v1/events/<uuid>/` → `Events.views.EventDetailView` |
| Event approval workflow | ✅ | `approved=False` by default; admin flips it via `PATCH /api/v1/admin/approve-event/<uuid>/` |
| List unapproved events (admin only) | ✅ | `GET /api/v1/unapproved-events/` → `Users.views.ListUnApprovedEvents` |
| Tags field | ⚠️ | Stored as stringified Python list (`eval()` on read) — functional but fragile |
| Search events by name, city, category | ⚠️ | `search_fields` declared in `EventView` but `SearchFilter` backend not added to `filter_backends` list — search is **not active** |
| Trending events (admin curates list) | ✅ | `GET /api/v1/trending-events/` + `PATCH /api/v1/update-trending-events/` |
| Event cancellation / deletion | ⚠️ | Delete is available on `EventDetailView` (owner only), but no cascade-cleanup of sold tickets / refunds |

---

### 5.5 Ticket Categories and Ticket Types

| Feature | Status | Location |
|---|---|---|
| Event categories (CRUD, admin-write / public-read) | ✅ | `GET/POST /api/v1/categories/` → `Events.views.CategoryView` |
| Case-insensitive duplicate prevention on categories | ✅ | `Category.clean()` + `CategorySerializer.validate()` |
| Multiple ticket tiers per event (TicketPrice) | ✅ | `POST /api/v1/create/event-ticket/` → `Events.views.CreateEventTicketPrice` |
| Free ticket support (`is_free=True` forces `price=0`) | ✅ | `TicketPrice.save()` override |
| Ticket label (e.g. "VIP", "General", "Early Bird") | ✅ | `TicketPrice.label` field |
| Ticket description | ✅ | `TicketPrice.description` field |
| Ticket quantity limit per tier | ✅ | `TicketPrice.qty` field |

---

### 5.6 Ticket Availability and Inventory Management

| Feature | Status | Location |
|---|---|---|
| Available tickets counter (`qty - sold`) | ✅ | `TicketPrice.get_tickets_available()` method |
| Sold-out check before add-to-cart | ✅ | `BuyTicketView.post()` checks `get_tickets_available() == 0` |
| Quantity exceeds available check | ✅ | `BuyTicketView.post()` checks `available < requested_qty` |
| `sold` counter incremented on successful payment | ✅ | `create_payment_record()` Celery task: `F('sold') + ticket.qty` (race-condition safe via `F()`) |
| Concurrent oversell protection (DB-level) | ❌ | No `select_for_update()` lock around the availability check → race condition possible under load |

---

### 5.7 Ticket Purchasing and Order Processing

| Feature | Status | Location |
|---|---|---|
| Add ticket to cart (creates `BuyTicket` + `OrderTicket`) | ✅ | `POST /api/v1/buy-ticket/<ticket_id>/` |
| Idempotent cart: updating qty re-uses existing `BuyTicket` | ✅ | `BuyTicket.objects.get_or_create` pattern in `BuyTicketView` |
| Specify recipient emails (one per ticket) | ✅ | `BuyTicketSerializer.validate()` — defaults to buyer's email if not provided |
| View checkout summary (event, tickets, total) | ✅ | `GET /api/v1/make-payment/<order_id>/` → `CheckoutSerializer` |
| Remove ticket from cart | ⚠️ | `POST /api/v1/remove-ticket/<pk>/` → `RemoveTicketView` exists but calls `BuyTicket.objects.delete(...)` (invalid — should be `BuyTicket.objects.get(...).delete()`) — **broken** |
| Order status: `not completed` → `completed` on payment | ✅ | `create_payment_record()` task |
| Free ticket checkout (bypasses Paystack) | ✅ | `Makepayment.post()`: if `price == 0`, calls `create_payment_record.delay()` directly |

---

### 5.8 Payment Processing and Transaction Verification

| Feature | Status | Location |
|---|---|---|
| Paystack transaction initialisation | ✅ | `Transactions.views.Makepayment.post()` → calls `api.paystack.co/transaction/initialize` |
| Paystack webhook receiver (`charge.success`) | ✅ | `POST /api/v1/paystack-webhook/` → `PayStack_Webhook` |
| Paystack webhook receiver (`charge.failed`) | ✅ | Same view, `elif data['event'] == 'charge.failed'` branch |
| Webhook signature verification (HMAC) | ❌ | **Not implemented** — critical security gap; any caller can trigger ticket generation |
| Payment record creation (internal reference code) | ✅ | `create_payment_record()` generates a 20-char alphanumeric ref via `generate_ref_code()` |
| Variable `p` bug in Makepayment | ⚠️ | Line 49 of `Transactions/views.py`: `str(p)` should be `str(pk)` — **NameError at runtime** |

---

### 5.9 Ticket Generation and Unique Identifiers

| Feature | Status | Location |
|---|---|---|
| Unique 16-digit numeric key per `SoldTicket` | ✅ | `generate_key()` in `Transactions/tasks.py` |
| `SoldTicket` model (links payment, ticket tier, user, key, used flag) | ✅ | `Transactions.models.SoldTicket` |
| PDF ticket generation (via pdfkit / wkhtmltopdf) | ✅ | `generate_pdf()` + `pdf.html` template |
| PDF styled as a physical ticket card (black, coral-bordered) | ✅ | `templates/pdf.html` with embedded CSS |
| Ticket label badge rendered on PDF | ✅ | `pdf.html` renders `{{ label }}` in a coloured badge |
| Multi-ticket PDF (one card per ticket in a single PDF) | ✅ | `pdf.html` loops over `data` list when emailing to a single address |

---

### 5.10 QR Code Generation and Ticket Validation

| Feature | Status | Location |
|---|---|---|
| QR code generated per `SoldTicket` | ✅ | `generate_qrcode(url)` in `Transactions/tasks.py` using `qrcode` library |
| QR code encodes validation URL | ✅ | URL: `ALLOWED_HOSTS[0] + /api/v1/verify-qrcode/<event_id>/<key>/` |
| QR code embedded in PDF as base64 PNG | ✅ | `pdf.html`: `<img src="data:image/png;base64, {{ qrcode }}">` |
| QR code validation endpoint | ✅ | `GET /api/v1/verify-qrcode/<event_id>/<key>/` → `VerifyQrcode` |
| Validation response (valid: true/false + event info) | ✅ | Returns `{valid: True, event: {id, name, label}}` or `{valid: False}` |
| Mark ticket as used on scan | ❌ | `VerifyQrcode` reads `used=False` in the query but **never sets `used=True`** — tickets can be scanned unlimited times |
| QR code URL uses `ALLOWED_HOSTS[0]` as hostname | ⚠️ | `ALLOWED_HOSTS = ['*']` so the URL becomes `*/api/v1/verify-qrcode/...` — invalid URL |

---

### 5.11 Event Check-in and Attendance Tracking

| Feature | Status | Location |
|---|---|---|
| `SoldTicket.used` boolean flag | ✅ | `Transactions.models.SoldTicket.used` (default=False) |
| Check-in via QR scan (UI/scanner app) | ❌ | Backend endpoint exists but does not mark tickets as used (see above) |
| Attendance report / count | ❌ | Not implemented |

---

### 5.12 Refunds and Cancellations

| Feature | Status | Location |
|---|---|---|
| Refund processing | ❌ | Not implemented |
| Order/ticket cancellation by user | ❌ | Not implemented |
| `payment_failed` task (cleans up BuyTickets) | ✅ | `Transactions.tasks.payment_failed()` deletes the order's tickets on failure |

---

### 5.13 Notifications and Email Services

| Feature | Status | Location |
|---|---|---|
| Email verification on registration | ✅ | allauth sends verification email; `adapter.py` customises the confirmation URL |
| Password reset email | ✅ | `dj_rest_auth` password reset flow |
| Ticket delivery email (HTML body + PDF attachment) | ✅ | `create_ticket()` in `Transactions/tasks.py`; `ticket.html` for body, `pdf.html` for PDF |
| Email dispatched asynchronously via Celery | ✅ | `create_ticket()` is called inside the `@shared_task create_payment_record()` |
| Email backend: Gmail SMTP | ✅ | `settings.py: EMAIL_HOST='smtp.gmail.com'`, port 587, TLS |
| In-app notifications | ❌ | Not implemented |
| SMS / push notifications | ❌ | Not implemented |

---

### 5.14 Administrative Functionality

| Feature | Status | Location |
|---|---|---|
| Django Admin panel | ✅ | `/admin/` — all models registered |
| Admin: approve event via bulk action | ✅ | `Events.admin.approve_event` action |
| Admin: Event with inline TicketPrice | ✅ | `Event_priceinline` in `Events.admin` |
| Admin: filter events by date, city, category | ✅ | `EventAdmin.list_filter` |
| Admin: search events by name, city, state | ✅ | `EventAdmin.search_fields` |
| Admin: deactivate sold tickets (action) | ⚠️ | `deactivate_tickets` action sets `inactive=True` — **field does not exist** on `SoldTicket` model, will raise `FieldError` |
| API: approve event (staff only) | ✅ | `PATCH /api/v1/admin/approve-event/<uuid>/` → `ADMIN.views.UpdateEventstatus` |
| API: list unapproved events (staff only) | ✅ | `GET /api/v1/unapproved-events/` → `Users.views.ListUnApprovedEvents` |
| API: set trending events (staff only) | ✅ | `PATCH /api/v1/update-trending-events/` |

---

### 5.15 Reporting and Analytics

| Feature | Status | Location |
|---|---|---|
| Organiser: total revenue earned | ✅ | `User.get_total_amount_earned()` aggregates `Payment.amount` for user's events |
| Organiser: total tickets sold across all events | ✅ | `User.get_total_tickets_sold()` counts `SoldTicket` |
| Organiser: total events created | ✅ | `User.get_total_event_created()` |
| Per-event: total tickets sold | ✅ | `Event.total_tickets_sold()` sums `TicketPrice.sold` |
| Per-ticket-tier: available count | ✅ | `TicketPrice.get_tickets_available()` |
| Revenue breakdown per event | ❌ | Not implemented |
| Admin-wide platform analytics | ❌ | Not implemented |
| Export / reporting endpoints | ❌ | Not implemented |

---

### 5.16 API Documentation

| Feature | Status | Location |
|---|---|---|
| Swagger UI | ✅ | `GET /` (root URL) → drf-yasg SwaggerUI |
| ReDoc | ✅ | `GET /redoc/` → drf-yasg ReDoc |
| Swagger login/logout config | ✅ | `SWAGGER_SETTINGS` in `settings.py` |

---

## 6. Database Architecture

### 6.1 Database Engine and ORM

- **Engine:** PostgreSQL 15.2
- **ORM:** Django ORM (via `django.db.backends.postgresql` + `psycopg2-binary`)
- **Extensions used:** `django.contrib.postgres` (installed but `ArrayField` not yet used — tags stored as `CharField`)

### 6.2 Entity-Relationship Overview

```
Users_User (UUID PK)
  │
  ├──< Events_Event (UUID PK, FK→User nullable SET_NULL)
  │       │
  │       ├──< Events_TicketPrice (BigInt PK, FK→Event CASCADE)
  │       │       │
  │       │       └──< Events_BuyTicket (UUID PK, FK→TicketPrice SET_NULL)
  │       │
  │       ├──< Events_OrderTicket (UUID PK, FK→Event SET_NULL, FK→User CASCADE)
  │       │       │
  │       │       └──< Events_BuyTicket (UUID PK, FK→OrderTicket CASCADE)
  │       │               └── Transactions_SoldTicket (UUID PK, FK→Payment, FK→TicketPrice SET_NULL, FK→OrderTicket SET_NULL, FK→User SET_NULL)
  │       │
  │       └──M2M── Events_Category (name PK)
  │
  ├──< Transactions_Payment (UUID PK, FK→User SET_NULL, 1:1→OrderTicket CASCADE)
  │       └──< Transactions_SoldTicket
  │
  └── Events_TrendingEvents (BigInt PK)
          └──M2M── Events_Event
```

### 6.3 Table Definitions

#### `Users_User`
| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK, default=uuid4 |
| `email` | VARCHAR(255) | UNIQUE, NOT NULL |
| `first_name` | VARCHAR(100) | NULL |
| `last_name` | VARCHAR(100) | NULL |
| `password` | VARCHAR(128) | NOT NULL (hashed) |
| `last_login` | TIMESTAMPTZ | NULL |
| `is_active` | BOOLEAN | default=True |
| `is_staff` | BOOLEAN | default=False |
| `is_superuser` | BOOLEAN | default=False |

#### `Events_Category`
| Column | Type | Constraints |
|---|---|---|
| `name` | VARCHAR(50) | PK, UNIQUE |

#### `Events_Event`
| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK, default=uuid4 |
| `user_id` | UUID | FK→User, NULL, SET_NULL |
| `name` | VARCHAR(500) | NOT NULL |
| `country` | VARCHAR(300) | NOT NULL |
| `city` | VARCHAR(300) | NOT NULL |
| `state` | VARCHAR(300) | NOT NULL |
| `address` | VARCHAR(400) | NOT NULL |
| `tags` | VARCHAR(500) | default=`[]`, blank |
| `description` | TEXT | NOT NULL |
| `image` | VARCHAR(255) | NULL, blank (Cloudinary public_id) |
| `approved` | BOOLEAN | default=False |
| `date_added` | TIMESTAMPTZ | auto_now_add |
| `start_date` | TIMESTAMPTZ | NOT NULL |
| `end_date` | TIMESTAMPTZ | NOT NULL |

**Index:** `(date_added, approved)` — composite index for the common "list approved events ordered by date" query.

#### `Events_TicketPrice`
| Column | Type | Constraints |
|---|---|---|
| `id` | BIGINT | PK, auto-increment |
| `event_id` | UUID | FK→Event, CASCADE |
| `label` | VARCHAR(50) | NOT NULL |
| `price` | FLOAT | default=0 |
| `description` | TEXT | NOT NULL |
| `is_free` | BOOLEAN | default=False |
| `sold` | POSITIVE INT | default=0 |
| `qty` | POSITIVE INT | default=0 |

#### `Events_OrderTicket`
| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK, default=uuid4 |
| `event_id` | UUID | FK→Event, NULL, SET_NULL |
| `user_id` | UUID | FK→User, NULL, CASCADE |
| `status` | VARCHAR(20) | choices: completed/not completed; default='not completed' |
| `date` | TIMESTAMPTZ | auto_now_add |

#### `Events_BuyTicket`
| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK, default=uuid4 |
| `user_id` | UUID | FK→User, NULL, CASCADE |
| `event_ticket_id` | BIGINT | FK→TicketPrice, NULL, SET_NULL |
| `order_id` | UUID | FK→OrderTicket, CASCADE |
| `qty` | POSITIVE INT | default=1 |
| `emails` | VARCHAR(9000) | NULL, blank (stores JSON-like list as string) |
| `date` | TIMESTAMPTZ | auto_now_add |
| `completed` | BOOLEAN | default=False |

#### `Transactions_Payment`
| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK, default=uuid4 |
| `user_id` | UUID | FK→User, NULL, SET_NULL |
| `payment_id` | VARCHAR(30) | NOT NULL (internal ref code) |
| `amount` | FLOAT | NOT NULL |
| `ticket_id` | UUID | FK→OrderTicket 1:1, CASCADE |
| `date` | TIMESTAMPTZ | auto_now_add |

#### `Transactions_SoldTicket`
| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK, default=uuid4 |
| `payment_id` | UUID | FK→Payment, CASCADE |
| `ticket_id` | BIGINT | FK→TicketPrice, NULL, SET_NULL |
| `event_id` | UUID | FK→OrderTicket, NULL, SET_NULL |
| `user_id` | UUID | FK→User, NULL, SET_NULL |
| `key` | VARCHAR(16) | NOT NULL (16-digit validation key) |
| `used` | BOOLEAN | default=False |

#### `Events_TrendingEvents`
| Column | Type | Constraints |
|---|---|---|
| `id` | BIGINT | PK, auto-increment |

+ M2M join table `Events_TrendingEvents_events (trendingevents_id, event_id)`

### 6.4 Migration state

There are **2 migrations per app** (except ADMIN which has none). The split between `0001` and `0002` in Events and Transactions was needed to break the circular dependency between `Events` ↔ `Users` ↔ `Transactions` at the database level.

```
Users:        0001_initial
Events:       0001_initial → 0002_initial
Transactions: 0001_initial → 0002_initial
ADMIN:        (no migrations)
```

---

## 7. Local Development Setup Guide

### 7.1 Prerequisites

| Requirement | Minimum version | Notes |
|---|---|---|
| Python | 3.9 | Matches the Dockerfile base image |
| pip | latest | Comes with Python |
| PostgreSQL | 13+ (15 recommended) | Or run via Docker |
| Redis | 6+ | Or run via Docker |
| `wkhtmltopdf` | 0.12.6 | **Required by pdfkit** — must be installed on the host OS separately |
| Docker & Docker Compose | Docker 20+ | Only if using the Docker path |
| Git | any | To clone the repo |

> [!IMPORTANT]
> **`wkhtmltopdf` is a system-level dependency** — it is not a Python package and is not declared in `requirements.txt`. Without it, PDF generation will silently fail or raise `OSError`. Install it before running the application.

---

### 7.2 Option A — Docker Compose (Recommended)

This is the simplest path. Docker Compose handles PostgreSQL, Redis, the Django app, and the Celery worker automatically.

#### Step 1 — Clone the repository
```bash
git clone <repo_url>
cd TicketPlug
```

#### Step 2 — Create the `.env` file
Copy the example below (see Section 8) and save it as `.env` in the project root.

#### Step 3 — Build and start all services
```bash
docker compose up --build
```

This will:
1. Pull `postgres:15.2-alpine` and `redis:alpine` images.
2. Build the application image from `Dockerfile`.
3. Run `server.sh` — which runs `makemigrations`, `migrate`, `createsuperuser`, `collectstatic`, then starts Gunicorn on port 8000.
4. Run `worker.sh` — which starts a Celery worker with 2 concurrent processes.

#### Step 4 — Access the application
- **API root / Swagger UI:** `http://localhost:8000/`
- **ReDoc:** `http://localhost:8000/redoc/`
- **Django Admin:** `http://localhost:8000/admin/`

---

### 7.3 Option B — Local Development (without Docker)

#### Step 1 — Clone the repository
```bash
git clone <repo_url>
cd TicketPlug
```

#### Step 2 — Create and activate a Python virtual environment
```bash
python -m venv venv
# On macOS/Linux:
source venv/bin/activate
# On Windows:
venv\Scripts\activate
```

#### Step 3 — Install Python dependencies
```bash
pip install -r requirements.txt
```

#### Step 4 — Install wkhtmltopdf (system dependency)
```bash
# Ubuntu / Debian
sudo apt-get install -y wkhtmltopdf

# macOS (Homebrew)
brew install wkhtmltopdf

# Windows
# Download installer from https://wkhtmltopdf.org/downloads.html
# Add the install directory to your PATH
```

#### Step 5 — Start PostgreSQL and create the database
```bash
# Start PostgreSQL if not running
# Then connect and create the database:
psql -U postgres
```
```sql
CREATE DATABASE ticketplug_db;
CREATE USER ticketplug_user WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE ticketplug_db TO ticketplug_user;
\q
```

#### Step 6 — Start Redis
```bash
# Ubuntu / Debian
sudo systemctl start redis

# macOS
brew services start redis

# Windows (via WSL or Docker)
docker run -d -p 6379:6379 redis:alpine
```

#### Step 7 — Create the `.env` file
Create a `.env` file in the project root. See Section 8 for a full annotated example.

#### Step 8 — Run database migrations
```bash
python manage.py migrate
```

> [!NOTE]
> `makemigrations` is already done — all migration files are committed. You only need `migrate` to apply them to your database. Only run `makemigrations` if you modify models.

#### Step 9 — Create a superuser
```bash
python manage.py createsuperuser
```
Enter an email and password when prompted. This account will have `is_superuser=True` and `is_staff=True`.

#### Step 10 — Collect static files
```bash
python manage.py collectstatic --noinput
```

#### Step 11 — Start the Celery worker (separate terminal)
```bash
celery -A Event_Project worker -l info -c 2
```

#### Step 12 — Start the Django development server
```bash
python manage.py runserver
```

The development server will be available at `http://127.0.0.1:8000/`.

---

### 7.4 Seeding Initial Data

There are no `fixtures` or management commands for seeding data. After setup:

1. **Log into Django Admin** at `/admin/` with the superuser account.
2. **Create Categories** (e.g. "Music", "Sports", "Tech") via `/admin/events/category/add/`.
3. **Set up a `TrendingEvents` record** at `/admin/events/trendingevents/add/` and assign events to it.

---

### 7.5 Common Startup Errors and Solutions

| Error | Cause | Solution |
|---|---|---|
| `django.db.utils.OperationalError: could not connect to server` | PostgreSQL not running or wrong credentials | Start PostgreSQL; verify `POSTGRES_*` env vars |
| `OSError: [Errno 2] No such file or directory: 'wkhtmltopdf'` | wkhtmltopdf not installed | Install wkhtmltopdf (see Step 4 above) |
| `KeyError: 'SECRET_KEY'` | Missing `.env` file | Create `.env` file with all required variables |
| `django.db.utils.ProgrammingError: relation "..." does not exist` | Migrations not run | Run `python manage.py migrate` |
| Celery `[ERROR/MainProcess] consumer: Cannot connect to redis://...` | Redis not running | Start Redis service |
| `ModuleNotFoundError: No module named 'cloudinary'` | Dependencies not installed | Run `pip install -r requirements.txt` |
| `NameError: name 'p' is not defined` | Bug in `Transactions/views.py` line 49 | Replace `str(p)` with `str(pk)` |
| Email verification link goes to wrong URL | `FRONTEND_URL` not set | Set `FRONTEND_URL` in `.env` to your frontend URL |
| `django.core.exceptions.ImproperlyConfigured: No SITE_ID` | `django.contrib.sites` requires a Site record | Run migrations (creates Site with id=1) or create one in Admin |

---

## 8. Environment Variables and External Integrations

### 8.1 Full `.env` Example

```dotenv
# ─── Django core ──────────────────────────────────────────────────────────────
# Generate with: python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
SECRET_KEY=your-very-long-random-secret-key-here

DEBUG=True

# ─── JWT signing key ──────────────────────────────────────────────────────────
# Use a separate random string from SECRET_KEY
SIGNING_KEY=another-very-long-random-signing-key-here

# ─── PostgreSQL database ──────────────────────────────────────────────────────
POSTGRES_USER=ticketplug_user
POSTGRES_PASSWORD=your_db_password
POSTGRES_NAME=ticketplug_db
# NOTE: settings.py hardcodes HOST='db' (the Docker service name).
# For local development outside Docker, change HOST to 'localhost' in settings.py.

# ─── Celery / Redis ───────────────────────────────────────────────────────────
CELERY_BROKER_URL=redis://redis:6379/0
# Use redis://localhost:6379/0 for local development without Docker
CELERY_RESULT_BACKEND=redis://redis:6379/0

# ─── Email (Gmail SMTP) ───────────────────────────────────────────────────────
EMAIL_HOST_USER=yourapp@gmail.com
# Use a Gmail App Password (not your account password)
# Generate at: https://myaccount.google.com/apppasswords
EMAIL_HOST_PASSWORD=your-gmail-app-password

# ─── Paystack payment gateway ─────────────────────────────────────────────────
# Get from https://dashboard.paystack.com/#/settings/developer
PAYSTACK_SECRET_KEY=sk_test_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# ─── Cloudinary media storage ─────────────────────────────────────────────────
# Get from https://console.cloudinary.com/
CLOUD_NAME=your-cloudinary-cloud-name
CLOUD_API_KEY=your-cloudinary-api-key
CLOUD_API_SECRET=your-cloudinary-api-secret

# ─── Frontend URL (for email verification links) ──────────────────────────────
# The URL of your frontend SPA — allauth's email confirmation link will point here
FRONTEND_URL=http://localhost:3000

# ─── Superuser (Docker server.sh only) ───────────────────────────────────────
DJANGO_SUPERUSER_EMAIL=admin@example.com
DJANGO_SUPERUSER_PASSWORD=your_admin_password
```

### 8.2 Variable Reference

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | ✅ | Django cryptographic signing key. Must be kept secret in production. |
| `DEBUG` | ✅ | `True` for development, `False` for production. |
| `SIGNING_KEY` | ✅ | JWT signing key used by `djangorestframework-simplejwt`. Keep separate from `SECRET_KEY`. |
| `POSTGRES_USER` | ✅ | PostgreSQL username. |
| `POSTGRES_PASSWORD` | ✅ | PostgreSQL password. |
| `POSTGRES_NAME` | ✅ | PostgreSQL database name. |
| `CELERY_BROKER_URL` | ✅ | Redis URL used as Celery's message broker. In Docker: `redis://redis:6379/0`. Local: `redis://localhost:6379/0`. |
| `CELERY_RESULT_BACKEND` | ✅ | Redis URL for storing Celery task results. Usually same as broker URL. |
| `EMAIL_HOST_USER` | ✅ | Gmail address used as the SMTP sender. |
| `EMAIL_HOST_PASSWORD` | ✅ | Gmail App Password (not account password). Enable 2FA and generate one at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords). |
| `PAYSTACK_SECRET_KEY` | ✅ | Paystack secret key. Use `sk_test_...` for development, `sk_live_...` for production. |
| `CLOUD_NAME` | ✅ | Cloudinary cloud name (visible on your Cloudinary dashboard). |
| `CLOUD_API_KEY` | ✅ | Cloudinary API key. |
| `CLOUD_API_SECRET` | ✅ | Cloudinary API secret. Keep private. |
| `FRONTEND_URL` | ✅ | Base URL of the frontend application. Used by `adapter.py` to build the email verification link. |
| `DJANGO_SUPERUSER_EMAIL` | Docker only | Email for the auto-created superuser in `server.sh`. |
| `DJANGO_SUPERUSER_PASSWORD` | Docker only | Password for the auto-created superuser. |

### 8.3 External Service Configuration

#### Paystack
1. Create an account at [dashboard.paystack.com](https://dashboard.paystack.com).
2. Copy your **Secret Key** (test or live) from the Developer settings.
3. In your Paystack dashboard, configure a **Webhook URL** pointing to: `https://yourdomain.com/api/v1/paystack-webhook/`
4. Subscribe to the events: `charge.success` and `charge.failed`.

> [!CAUTION]
> The webhook endpoint currently has **no HMAC signature verification**. Before going live, add verification using the `X-Paystack-Signature` header to prevent fraudulent webhook calls.

#### Cloudinary
1. Create an account at [cloudinary.com](https://cloudinary.com).
2. From your dashboard, copy `Cloud Name`, `API Key`, and `API Secret`.
3. No additional configuration needed — the Python SDK is configured entirely from the `.env` variables.

#### Gmail SMTP
1. Ensure 2-Step Verification is enabled on the Gmail account.
2. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) and generate an App Password for "Mail".
3. Use the generated 16-character password as `EMAIL_HOST_PASSWORD`.

#### wkhtmltopdf
- The `pdfkit` Python library is a wrapper around the `wkhtmltopdf` binary.
- It must be installed separately on the host OS or included in the Docker image.
- The current `Dockerfile` does **not** install `wkhtmltopdf` — this is a deployment gap.

> [!WARNING]
> The `Dockerfile` is missing the `wkhtmltopdf` installation step. PDF generation will fail in Docker until this is added:
> ```dockerfile
> RUN apt-get update && apt-get install -y wkhtmltopdf && rm -rf /var/lib/apt/lists/*
> ```
> Add this line before the `COPY requirements.txt .` line in the Dockerfile.

#### Database host for local development
`settings.py` hardcodes `'HOST': 'db'` (the Docker Compose service name). For local development without Docker, change this to `'HOST': 'localhost'` or add a `POSTGRES_HOST` env variable.

---

## 9. Recommended Development Roadmap

The following issues and improvements are listed in order of priority.

### 9.1 Critical Bugs (Fix Before Any Production Use)

| Priority | Issue | File | Fix |
|---|---|---|---|
| 🔴 P0 | **`NameError: name 'p' is not defined`** — payment initiation crashes at runtime | `Transactions/views.py:49` | Replace `str(p)` with `str(pk)` |
| 🔴 P0 | **No Paystack webhook signature verification** — any actor can trigger ticket generation by POSTing to the webhook | `Transactions/views.py: PayStack_Webhook` | Verify `X-Paystack-Signature` HMAC header against the request body using `PAYSTACK_SECRET_KEY` |
| 🔴 P0 | **Tickets are never marked as `used`** after QR scan — tickets can be scanned infinite times | `Transactions/views.py: VerifyQrcode` | After successful lookup, call `ticket.update(used=True)` |
| 🔴 P0 | **`wkhtmltopdf` missing from Dockerfile** — PDF generation fails in Docker | `Dockerfile` | Add `RUN apt-get update && apt-get install -y wkhtmltopdf` |
| 🔴 P0 | **`RemoveTicketView` is broken** — calls `BuyTicket.objects.delete(...)` instead of getting an instance first | `Events/views.py: RemoveTicketView` | Change to `BuyTicket.objects.get(...).delete()` |
| 🟠 P1 | **QR code URL invalid** — `ALLOWED_HOSTS=['*']` produces `*/api/v1/verify-qrcode/...` | `Transactions/tasks.py` + `settings.py` | Add a `BASE_URL` env var and use it to build the QR URL |
| 🟠 P1 | **`deactivate_tickets` admin action references non-existent `inactive` field** | `Transactions/admin.py` | Use `used=True` instead of `inactive=True` |
| 🟠 P1 | **`create_ticket()` bug in "single email" branch** — iterates `for t in range(ticket.qty)` then accesses `t.event_ticket` (int has no attribute) | `Transactions/tasks.py:73` | Should be `for _ in range(ticket.qty): ticket_tier = ticket.event_ticket` |
| 🟠 P1 | **Database host hardcoded as `'db'`** — breaks local dev without Docker | `Event_Project/settings.py:124` | Use `config('POSTGRES_HOST', default='db')` |

### 9.2 Security Improvements

- **Rate limiting** — Add `django-ratelimit` or DRF throttling to auth and payment endpoints.
- **`ALLOWED_HOSTS`** — Change from `['*']` to a specific list in production.
- **`CORS_ALLOW_ALL_ORIGINS=True`** — Restrict to specific frontend origins in production.
- **`CSRF_COOKIE_SECURE` / `SESSION_COOKIE_SECURE`** — Already `True`; ensure HTTPS in production.
- **Concurrent oversell protection** — Wrap the availability check and `BuyTicket` creation in `select_for_update()` to prevent race conditions under high load.

### 9.3 Missing Features to Implement

- **Profile update endpoint** — `PATCH /api/v1/user/` to allow users to change their name.
- **Event search** — Add `SearchFilter` to `filter_backends` in `EventView`.
- **Fix tags storage** — Replace `CharField` with `django.contrib.postgres.fields.ArrayField`.
- **Mark ticket as used** — Implement the `used=True` update in `VerifyQrcode`.
- **Refunds** — Integrate Paystack's refund API; add a `Refund` model.
- **Wallet / payout system** — The commented-out `Withdrawal` model suggests this was planned; design and implement it.
- **Pagination on all list endpoints** — Verify all `ListAPIView`s respect the global `LimitOffsetPagination` setting.
- **Social auth** — Configure `allauth` social providers (Google, Facebook) if desired.
- **Event search by date range** — Allow filtering events by `start_date__gte` / `start_date__lte`.

### 9.4 Code Quality and Maintenance

- **Deduplication** — Remove the duplicated `UpdateEventstatus` view from `Users/views.py`; the `ADMIN` app is the correct home.
- **Naming consistency** — Rename the `ADMIN` directory to `Admin` (or vice versa in `apps.py`) to match the Django `AppConfig.name`.
- **`requirements.txt` cleanup** — `celery` and `python-decouple` are listed twice; `django-rest-swagger` is both installed and superseded by `drf-yasg`.
- **Test coverage** — All `tests.py` files are empty. Add unit tests for serializers, view logic, task functions, and permission classes.
- **Logging** — Replace `print()` statements in `tasks.py` with Python's `logging` module.
- **Type hints** — Add type annotations to service functions (e.g. `create_ticket`, `generate_qrcode`) for better IDE support and documentation.
- **Celery task error handling** — `create_payment_record` silently catches all exceptions with `except Exception as e: print(e)`. Add proper error logging and consider a retry strategy.

