# Padvault Backend — Technical Documentation

## Table of Contents

1. [Overview](#overview)
2. [Technology Stack](#technology-stack)
3. [Project Structure](#project-structure)
4. [Authentication & Security](#authentication--security)
5. [App: Users](#app-users)
6. [App: Properties](#app-properties)
7. [App: Rent](#app-rent)
8. [App: Invoices](#app-invoices)
9. [App: Transactions](#app-transactions)
10. [App: Bookings](#app-bookings)
11. [App: Maintenance](#app-maintenance)
12. [App: Notifications](#app-notifications)
13. [App: Admin / HQ](#app-admin--hq)
14. [Utilities](#utilities)
15. [Payment System — Monnify](#payment-system--monnify)
16. [Storage — Cloudinary](#storage--cloudinary)
17. [Email System — Brevo](#email-system--brevo)
18. [PDF Generation](#pdf-generation)
19. [Complete API Reference](#complete-api-reference)

---

## Overview

Padvault is a property management SaaS platform. The backend is a Django REST Framework service that exposes a JSON API consumed exclusively by the React frontend. It handles:

- Landlord and property management
- Tenant lease lifecycle (initiation → approval → e-signature → payment schedule)
- Invoice generation and payment collection via Monnify
- Short-term booking management
- Maintenance request tracking
- Web push notifications
- PDF lease document generation and cloud storage
- A superadmin panel (padvault-hq)

The API is **not a public API** — it is a private service for the Padvault web application. All protected endpoints require a valid JWT stored in an HTTP-only cookie.

---

## Technology Stack

| Concern | Technology |
|---------|------------|
| Framework | Django 4.x + Django REST Framework |
| Language | Python 3.x |
| Authentication | Custom JWT (HS256), stored in `padvault_token` HTTP-only cookie |
| Database | PostgreSQL |
| File Storage | Cloudinary (images: `resource_type="image"`, PDFs: `resource_type="raw"`) |
| Email | Brevo (formerly Sendinblue) via direct HTTP API |
| Payments | Monnify (Checkout SDK + HMAC-SHA512 webhook) |
| PDF Generation | xhtml2pdf (pisa) from HTML templates |
| Push Notifications | Web Push Protocol with VAPID keys |
| Rate Limiting | Custom in-memory rate limiter (`utils/rate_limit.py`) |

---

## Project Structure

```
rent-mgt-core-service/
└── rent_core_service/
    ├── rent_core_service/       # Django project settings, root URL conf
    │   ├── settings.py
    │   ├── urls.py              # Root URL dispatcher
    │   ├── wsgi.py
    │   └── asgi.py
    ├── Users/                   # Auth, profiles, KYC, subscriptions
    ├── Properties/              # Property CRUD + public marketplace
    ├── Rent/                    # Leases, initiations, schedules, e-signatures
    ├── Invoices/                # Invoice lifecycle + Monnify payment portal
    ├── Transactions/            # Ledger + Monnify webhook handler
    ├── Bookings/                # Short-term booking management
    ├── Maintenance/             # Maintenance requests
    ├── Notifications/           # Web push subscriptions + notification records
    ├── Admin/                   # Padvault-HQ superadmin API
    ├── utils/
    │   ├── auth_middleware.py   # JWT authentication middleware
    │   ├── reconciliation.py   # Central payment reconciliation engine
    │   ├── email.py            # Brevo email manager
    │   ├── monnify.py          # Monnify payment provider
    │   ├── push_notifications.py # VAPID web push
    │   ├── rate_limit.py       # In-memory rate limiter
    │   └── calendar.py         # Booking conflict detection
    └── templates/
        └── emails/             # HTML email templates
```

---

## Authentication & Security

### JWT Token System

Padvault uses **custom JWT tokens** — not Django's built-in session auth, not DRF's TokenAuthentication, and not `djangorestframework-simplejwt`. Tokens are issued by a `token_manager` class in `Users/models.py` using HS256 signing.

The token is stored in a **cookie named `padvault_token`**. The frontend's axios client sends `withCredentials: true` on every request, which causes the browser to automatically include the cookie.

```
Cookie: padvault_token=<jwt>
```

### TokenAuthenticationMiddleware

Every request passes through `utils/auth_middleware.py`. The middleware:

1. Checks if the request path is a public endpoint (exact match or regex pattern). If so, passes through immediately.
2. Extracts the JWT from `padvault_token` cookie. Falls back to `Authorization: JWT <token>` header if the cookie is absent.
3. Validates the token via `token_manager.validate_token()`.
4. Loads the `User` object from the database and attaches it to `request.user`.
5. Checks that `user.isactive == True`. Returns `401` if the account is deactivated.

### Public Endpoints (No Auth Required)

**Exact paths:**
- `POST /api/users/login/`
- `POST /api/users/register/`
- `GET /health/`
- `POST /api/transactions/monnify-webhook/`
- `GET /api/properties/`
- `GET /api/properties/search/`
- `GET /api/properties/filter/`
- `GET /api/properties/categories/`
- `GET /api/properties/featured/`

**Regex patterns:**
- `GET /api/properties/<id>/view/` — public property detail
- `GET /api/rent/lease/<uuid>/` — public lease viewer
- `POST /api/rent/lease/<uuid>/sign/` — tenant e-signature
- `POST /api/rent/initiations/public/` — anonymous rental application
- `GET /api/rent/documents/<uuid>/view/` — PDF proxy (document viewer)

All invoice public endpoints and payment portal endpoints are also excluded from auth via the `AllowAny` permission class on those specific views (additionally bypassing the middleware check).

### Admin Impersonation

Admins can impersonate a user by obtaining an `padvault_impersonation_token` cookie (issued by the `/api/padvault-hq/users/<id>/impersonate/` endpoint). When both cookies are present:

- `padvault_token` is validated as the **admin's** identity
- `padvault_impersonation_token` is validated as the **impersonated user's** identity
- `request.user` is set to the impersonated user
- `request.impersonator` is set to the admin user

This allows admins to browse the system as any user for support purposes.

### CSRF

The frontend sends the Django CSRF token via the `X-CSRFToken` header, reading it from the `csrftoken` cookie. This is configured in `axios.create()` via `xsrfCookieName: 'csrftoken'`.

### Rate Limiting

Custom decorator-based rate limiting is applied to individual views using `@method_decorator(rate_limit(limit, window_seconds, key_prefix))`. Rates are tracked per IP address in memory. Example limits:

| Endpoint | Limit |
|----------|-------|
| Public property list | 60/min |
| Public property detail | 100/min |
| Public initiation create | 10/hour |
| Document proxy | Custom throttle classes |

### Permissions

Views use either:
- `AllowAny` — public endpoints
- `IsLandlordOrAdmin` — a custom DRF permission class requiring `user.role in ['landlord', 'admin']`

---

## App: Users

### Purpose

Handles all user account operations: registration with email OTP verification, JWT login/logout, profile management, password reset, KYC verification, Monnify subscription paywall, and profile picture upload.

### Model: `User`

Custom user model extending Django's base. Key fields:

| Field | Type | Notes |
|-------|------|-------|
| `id` | AutoField | Primary key |
| `email` | EmailField unique | Login identifier |
| `firstname`, `lastname` | CharField | Display name |
| `role` | CharField | `'landlord'` or `'admin'` |
| `isactive` | BooleanField | Soft deactivation |
| `email_verified` | BooleanField | Must verify OTP before login |
| `registration_step` | CharField | Onboarding progress: `'email_verified'`, `'profile_setup'`, `'complete'` |
| `subscription_tier` | CharField | `'free'` or `'premium'` |
| `subscription_status` | CharField | `'active'`, `'expired'`, `'cancelled'` |
| `subscription_expires_at` | DateTimeField | Premium expiry |
| `kyc_status` | CharField | `'not_submitted'`, `'pending'`, `'verified'`, `'rejected'` |
| `saved_signature` | TextField | Base64 PNG of landlord's digital signature |
| `profile_picture` | URLField | Cloudinary URL |
| `monnify_subaccount_code` | CharField | Monnify split payment recipient |
| `created_at` | DateTimeField | Account creation timestamp |

### Authentication Flow

**Registration:**
1. `POST /api/users/register/` — creates User with `email_verified=False`, sends OTP email via Brevo
2. `POST /api/users/verify-email/` — validates OTP, sets `email_verified=True`, issues JWT cookie
3. `POST /api/users/resend-otp/` — resends OTP if expired

**Login:**
1. `POST /api/users/login/` — validates credentials, checks `email_verified` and `isactive`, issues `padvault_token` JWT cookie in response
2. `POST /api/users/auth/google/` — authenticates via Google OAuth, dynamically matches or provisions a user, securely generates random passwords, and issues a standard `padvault_token` JWT cookie for session isolation.

**Logout:**
- `POST /api/users/logout/` — clears the `padvault_token` cookie
- `POST /api/users/logout/all/` — invalidates all sessions (implementation-specific)

**Password Reset:**
1. `POST /api/users/forgot-password/` — sends reset link/OTP to email
2. `POST /api/users/reset-password/` — validates token, updates password

### Profile & Settings

- `GET /api/users/profile/` — returns full user profile
- `PUT /api/users/profile/update/` — update firstname, lastname, phone, etc.
- `POST /api/users/profile/picture/` — upload profile picture (multipart), stored in Cloudinary
- `POST /api/users/change-password/` — change password (requires current password)
- `DELETE /api/users/profile/delete/` — delete account (requires password confirmation)

### KYC

- `POST /api/users/kyc-verify/` — submit KYC data; sets `kyc_status='pending'`
- `GET /api/users/banks/` — securely fetches and caches the live list of supported Nigerian banks directly from Monnify for KYC routing
- Admin can override via `PATCH /api/padvault-hq/kyc/<id>/override/`

### Subscription

- `POST /api/users/subscribe/` — initiates premium subscription payment via Monnify, creates a subscription invoice, returns `{ checkout_url, payment_reference }`
- `POST /api/users/verify-subscription/` — polls Monnify to confirm payment status after the user returns from checkout. Accepts `{ payment_reference }` in the request body. Validates the reference belongs to the authenticated user (`SUB-<user_id>-...` prefix), then calls `MonnifyProvider.verify_transaction()`. If `paymentStatus == 'PAID'`, dispatches to `process_monnify_webhook()` (idempotent — no-ops if the webhook already ran). Returns `{ success, paid, subscription_tier, subscription_expires_at }`. Solves the case where the Monnify webhook is delayed and the user returns from checkout still showing as Free tier.

### Contact

- `POST /api/users/contact/` — stores a support message in the database; visible in admin HQ

---

## App: Properties

### Purpose

Manages property listings for landlords. Exposes a public marketplace API and a private landlord CRUD API.

### Model: `properties` (lowercase)

| Field | Type | Notes |
|-------|------|-------|
| `id` | AutoField | Primary key |
| `landlord` | FK → User | Owner |
| `address_id` | FK → Address | Linked address record |
| `title` | CharField | Listing title |
| `description` | TextField | Full description |
| `property_type` | CharField | `apartment`, `house`, `condo`, `studio`, `commercial`, `bungalow`, `duplex`, `other` |
| `listing_type` | CharField | `lease`, `short_term`, `hybrid` |
| `status` | CharField | `available`, `occupied`, `under_maintenance`, `unavailable` |
| `bedrooms`, `bathrooms` | IntegerField | |
| `monthly_rent` | DecimalField | For lease/hybrid |
| `yearly_rent` | DecimalField | Annual equivalent |
| `nightly_rate` | DecimalField | For short_term/hybrid |
| `min_nights` | IntegerField | Short-term minimum |
| `is_published` | BooleanField | Controls marketplace visibility |
| `is_featured` | BooleanField | Featured placement |
| `is_flagged` | BooleanField | Admin-set flag for suspicious/fraudulent listings |
| `flag_reason` | TextField (nullable) | Admin's reason for flagging |
| `main_image` | URLField | Cloudinary URL |
| `image_urls` | JSONField | Gallery array |
| `views_count` | IntegerField | View counter |
| `created_at`, `updated_at` | DateTimeField | |

### Model: `Address`

| Field | Type |
|-------|------|
| `street` | CharField |
| `city` | CharField |
| `state_province` | CharField |
| `country` | CharField (default `'Nigeria'`) |

### Pricing Logic

- **Lease:** `price = monthly_rent`, `price_period = "month"`
- **Short-term:** `price = nightly_rate`, `price_period = "night"`
- **Hybrid:** `price = monthly_rent` (list view default), exposes both `monthly_rent` and `nightly_rate`

### Public Marketplace API

All endpoints are unauthenticated:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/properties/` | Paginated list with search + filters |
| GET | `/api/properties/meta/` | Price ranges, locations, types for filter UI |
| GET | `/api/properties/<id>/view/` | Property detail with landlord trust info |
| GET | `/api/properties/featured/` | Featured listings (up to 6) |
| GET | `/api/properties/categories/` | Counts per property type |
| GET | `/api/properties/status-counts/` | Counts per status |

**Search & Filter Query Params (`GET /api/properties/`):**

| Param | Effect |
|-------|--------|
| `q` | Full-text search across title, description, city, state |
| `type` | Filter by `property_type` |
| `listing_type` | Filter by `listing_type` |
| `min_price` / `max_price` | Filter by monthly_rent or nightly_rate |
| `bedrooms` / `bathrooms` | Exact match |
| `page` / `limit` | Pagination (default limit=12) |

### Landlord CRUD API

All endpoints require `IsLandlordOrAdmin`:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/properties/landlord/properties/` | List own properties |
| GET | `/api/properties/landlord/<id>/` | Property detail |
| POST | `/api/properties/landlord/create/` | Create new property |
| PATCH | `/api/properties/landlord/<id>/` | Update property fields |
| PATCH | `/api/properties/landlord/<id>/status/` | Update status only |
| DELETE | `/api/properties/landlord/<id>/` | Delete property |
| POST | `/api/properties/<id>/images/upload/` | Upload image to Cloudinary |
| DELETE | `/api/properties/<id>/images/remove/` | Remove image |
| GET | `/api/properties/<id>/assets/` | List property assets/amenities |
| POST | `/api/properties/<id>/assets/` | Add asset |
| PUT | `/api/properties/<id>/assets/<assetId>/` | Update asset |
| DELETE | `/api/properties/<id>/assets/<assetId>/` | Remove asset |
| GET | `/api/properties/<id>/availability/` | Check availability |

---

## App: Rent

### Purpose

The core business domain. Manages the full lease lifecycle:

1. **Initiation** — a prospective tenant applies for a property
2. **Approval** — landlord approves or rejects
3. **E-Signature** — tenant digitally signs the lease agreement
4. **Lease** — active rent record with payment schedule
5. **Payments** — installment-based payment tracking
6. **Document** — PDF lease stored in Cloudinary, accessible via proxy

### Models

#### `RentInitiation`

| Field | Type | Notes |
|-------|------|-------|
| `rental_property` | FK → properties | Target property |
| `tenant` | FK → User (nullable) | Registered tenant account |
| `landlord` | FK → User | Receiving landlord |
| `tenant_name` | CharField | Required for anonymous applications |
| `tenant_email` | EmailField | Required for anonymous applications |
| `tenant_phone` | CharField | Optional |
| `proposed_start_date` | DateField | Required |
| `proposed_end_date` | DateField | Required |
| `proposed_rent_type` | CharField | `monthly` (default), `yearly`, `quarterly`, `bi_annually`, `custom` |
| `proposed_amount` | DecimalField | Single-period rent |
| `proposed_security_deposit` | DecimalField | Default 0 |
| `message` | TextField | Optional message to landlord |
| `status` | CharField | `pending`, `approved`, `rejected`, `expired` |
| `rejection_reason` | TextField | Set on rejection |
| `expires_at` | DateTimeField | Auto-set to 7 days from creation |

*Security Note: The API serializer dynamically limits `proposed_end_date` to a maximum of 5 years (60 months) ahead of `proposed_start_date` to protect against infinite schedule generation.*

**`convert_to_rent()` method:** When approved, calculates `duration_months`, `total_periods`, and `total_amount`, then creates a `Rent` object and sets `status='approved'`.

#### `Rent`

| Field | Type | Notes |
|-------|------|-------|
| `rental_property` | FK → properties | |
| `tenant` | FK → User (nullable) | |
| `tenant_name`, `tenant_email`, `tenant_phone` | CharField | Denormalized tenant info |
| `rent_type` | CharField | Matches initiation's rent type |
| `amount` | DecimalField | Single-period amount |
| `start_date`, `end_date` | DateField | Lease duration |
| `duration_months` | IntegerField | Computed from dates |
| `total_amount` | DecimalField | `amount × total_periods` |
| `amount_paid`, `balance` | DecimalField | Updated on each payment |
| `payment_status` | CharField | `pending`, `paid`, `overdue`, `cancelled` |
| `total_periods` | IntegerField | Number of installments |
| `current_period` | IntegerField | Current installment number |
| `next_payment_date` | DateField | |
| `security_deposit` | DecimalField | |
| `deposit_status` | CharField | `pending`, `paid`, `refunded`, `deducted` |
| `lease_public_id` | UUIDField | UUID for public lease URL |
| `tenant_signature` | TextField | Base64 PNG of tenant's signature |
| `landlord_signature` | TextField | Copied from `landlord.saved_signature` |
| `lease_document_url` | URLField | Cloudinary raw URL of signed PDF |
| `is_signed` | BooleanField | True after signing completes |
| `signed_at` | DateTimeField | |

**`generate_schedule()` method:** Creates `PaymentSchedule` rows for each installment, spacing them by `period_delta` (relativedelta from dateutil).

**`mark_as_paid(amount)` method:** Increments `amount_paid`, recalculates `balance`. Sets `payment_status='paid'` when balance reaches 0.

**Properties:**
- `is_active` — True if today is between start/end date and not cancelled
- `progress_percentage` — `(amount_paid / total_amount) × 100`

#### `PaymentSchedule`

| Field | Type | Notes |
|-------|------|-------|
| `rent` | FK → Rent | |
| `installment_number` | PositiveIntegerField | 1-indexed |
| `due_date` | DateField | |
| `amount_due` | DecimalField | |
| `amount_paid` | DecimalField | Default 0 |
| `status` | CharField | `pending`, `partial`, `paid`, `overdue` |
| `paid_at` | DateTimeField | Null until paid |
| `invoice` | FK → Invoice (nullable) | Auto-generated invoice link |

Unique constraint: `(rent, installment_number)`

#### `RentPayment`

Manual payment record (used when landlord records cash/bank transfer payments directly):

| Field | Type |
|-------|------|
| `rent` | FK → Rent |
| `tenant` | FK → User (nullable) |
| `amount` | DecimalField |
| `payment_method` | CharField (`bank_transfer`, `card`, `mobile_money`, `cash`) |
| `payment_reference` | CharField (unique) |
| `payment_status` | CharField (`pending`, `completed`, `failed`, `refunded`) |
| `payment_date` | DateTimeField |
| `due_date` | DateField |
| `period_start`, `period_end` | DateField |
| `transaction` | FK → Transaction (nullable) |

### Views & Endpoints

#### Public (No Auth)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/rent/lease/<uuid>/` | Fetch lease for public signing page |
| POST | `/api/rent/lease/<uuid>/sign/` | Submit tenant signature + generate PDF |
| POST | `/api/rent/initiations/public/` | Anonymous property application (sends confirmation email to applicant + email and push notification to landlord) |
| GET | `/api/rent/documents/<uuid>/view/` | Proxy: fetch PDF from Cloudinary and serve |

#### Protected (IsLandlordOrAdmin)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/rent/` | List all leases for landlord's properties |
| GET | `/api/rent/<id>/` | Lease detail with full schedule |
| PATCH | `/api/rent/<id>/` | Update lease (tenant info, amount, dates) |
| PATCH | `/api/rent/<id>/cancel/` | Cancel lease |
| GET | `/api/rent/<id>/schedule/` | Payment schedule entries |
| GET | `/api/rent/<id>/payments/` | Manual payment records |
| POST | `/api/rent/<id>/payments/` | Record a manual payment |
| POST | `/api/rent/schedule/<id>/send-payment-email/` | Re-send payment email for installment |
| GET | `/api/rent/initiations/` | List all initiations |
| POST | `/api/rent/initiations/` | Create initiation (landlord-side) |
| PATCH | `/api/rent/initiations/<id>/approve/` | Approve → creates Rent + schedule |
| PATCH | `/api/rent/initiations/<id>/reject/` | Reject with reason |

### Signing Flow (PublicLeaseSignView)

`POST /api/rent/lease/<uuid>/sign/`

1. Validate that the lease exists and `is_signed=False`
2. Check that `landlord.saved_signature` exists (required for the document)
3. Validate `tenant_signature` is present in request body
4. Save `rent.tenant_signature` and `rent.landlord_signature`
5. Render the `emails/lease_document.html` template with full lease context
6. Generate PDF via `xhtml2pdf.pisa.CreatePDF()`
7. Upload PDF to Cloudinary as `resource_type="raw"`, `folder="padvault/leases"`, `public_id="lease_<uuid>.pdf"`
8. Save `rent.lease_document_url = upload_result['secure_url']`
9. Set `rent.is_signed=True`, `rent.signed_at=timezone.now()`
10. Email both parties via `EmailManager.send_final_lease_document()` with proxy URL (not direct Cloudinary URL)
11. Return `{ success: true, data: { lease_document_url, invoice_public_id } }`

The `invoice_public_id` in the response allows the frontend to redirect directly to the payment portal after signing.

### Document Proxy (DownloadLeaseView)

`GET /api/rent/documents/<uuid>/view/`

- No auth required (`AllowAny`)
- Rate-throttled (per-document and per-user/IP)
- Fetches the stored `lease_document_url` from Cloudinary via `requests.get()`
- Returns response bytes with `Content-Type: application/pdf`
- Logs errors if Cloudinary returns non-200

### Approval Flow (RentInitiationApproveView)

`PATCH /api/rent/initiations/<id>/approve/`

All operations run inside a single `transaction.atomic()` block:

1. Lock the property row with `select_for_update()` to prevent concurrent approvals
2. Run `check_booking_conflict()` to detect date overlaps
3. Auto-reject all other `pending` applications for the same property, updating their status to `rejected`
4. Call `initiation.convert_to_rent()` to create the `Rent` record
5. Call `rent.generate_schedule()` to create all `PaymentSchedule` rows
5. Generate the first invoice via `generate_invoice_for_schedule(first_installment)`
6. Send e-signature email to tenant via `EmailManager.send_lease_signature_email()`
7. Update property status to `'occupied'`
8. Send push notification to tenant

---

## App: Invoices

### Purpose

Manages the invoice lifecycle: creation, delivery, Monnify payment initialisation, webhook processing, and manual mark-as-paid. Invoices are the financial core of the platform — every payment event is anchored to an invoice.

### Model: `Invoice`

| Field | Type | Notes |
|-------|------|-------|
| `public_id` | UUIDField | Used in public payment URLs |
| `invoice_number` | CharField | Human-readable ID, e.g. `INV-20240001` |
| `issued_by` | FK → User (nullable) | Landlord |
| `issued_to_name` | CharField | Tenant display name |
| `issued_to_email` | EmailField | Tenant email for receipts |
| `rent` | FK → Rent (nullable) | Links to a lease |
| `booking` | FK → Booking (nullable) | Links to a booking |
| `status` | CharField | `draft`, `sent`, `paid`, `overdue`, `partial` |
| `total` | DecimalField | Invoice amount |
| `currency` | CharField | Default `NGN` |
| `due_date` | DateField | |
| `paid_at` | DateTimeField | Null until paid |
| `monnify_reference` | CharField | Stored after init-payment call |
| `notes` | TextField | `'Premium Subscription Renewal'` for subscription invoices |
| `created_at`, `updated_at` | DateTimeField | |

### Invoice Status Lifecycle

```
draft → sent → paid
              ↗
        partial
```

- `draft` — created but not yet sent
- `sent` — emailed to tenant; payment link is active
- `partial` — payment received but less than `total`
- `paid` — full payment reconciled
- `overdue` — past due_date and not paid (no auto-update; must be set manually or via cron)

### Views & Endpoints

#### Public (No Auth — Payment Portal)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/invoices/public/<public_id>/` | Fetch invoice for payment portal display |
| POST | `/api/invoices/public/<public_id>/init-payment/` | Initialise Monnify checkout |
| POST | `/api/invoices/public/<public_id>/verify-payment/` | Query Monnify and reconcile if paid |

**init-payment flow:**
1. Read `redirect_url` from the request body (the frontend passes `${window.location.origin}/pay/<publicId>`). Falls back to `https://padvault.io/pay/<publicId>` if absent. **HTTP_REFERER is not used** — it is unreliable across browsers and proxy configurations.
2. Generate a unique `transactionReference` (UUID)
3. Call `MonnifyProvider.initialize_transaction()` with amount, description, split payment config, and `redirectUrl`
4. Save `unique_reference` to `invoice.monnify_reference`
5. Return `{ checkoutUrl }` for frontend redirect to Monnify-hosted checkout

**verify-payment flow (idempotent):**
1. Fetch the stored `monnify_reference`
2. Call `MonnifyProvider.verify_transaction(reference)` to query Monnify API
3. If status is `PAID`, call `reconcile_payment(invoice, amount_paid, gateway_reference)`
4. Return current invoice state

#### Protected (IsLandlordOrAdmin)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/invoices/` | Paginated invoice list with status filter |
| GET | `/api/invoices/<id>/` | Invoice detail |
| POST | `/api/invoices/` | Create invoice manually |
| PATCH | `/api/invoices/<id>/mark-paid/` | Manual mark-as-paid (calls reconcile_payment) |

---

## App: Transactions

### Purpose

The financial ledger. Every payment — whether via Monnify webhook or manual recording — creates a `Transaction` row. Also hosts the Monnify webhook handler.

### Model: `Transaction`

| Field | Type | Notes |
|-------|------|-------|
| `reference` | CharField | Matches `invoice.invoice_number` for deduplication |
| `transaction_type` | CharField | `rent_payment`, `booking_fee`, `subscription` |
| `amount` | DecimalField | |
| `net_amount` | DecimalField | After fees |
| `payer` | FK → User (nullable) | |
| `payee` | FK → User (nullable) | Landlord |
| `status` | CharField | `pending`, `success`, `failed` |
| `description` | CharField | |
| `payment_gateway` | CharField | `'Monnify'` or `'Manual'` |
| `gateway_reference` | CharField | Monnify's transaction reference |
| `completed_at` | DateTimeField | |
| `created_at`, `updated_at` | DateTimeField | |

### Monnify Webhook Handler

`POST /api/transactions/monnify-webhook/`

This endpoint is public (no auth) and processes real-time payment notifications from Monnify.

**Webhook Processing Flow:**

1. Extract `monnifySignature` header and raw request body
2. Recompute HMAC-SHA512 of the JSON body using `settings.MONNIFY_SECRET_KEY`
3. Compare computed hash with `monnifySignature`. Return `400` on mismatch.
4. Parse the payload. If `paymentStatus == 'PAID'`:
   - Look up the `Invoice` by matching `transactionReference` against `invoice.monnify_reference`
   - Dispatch to a background thread to call `reconcile_payment(invoice, amount_paid, gateway_reference)`
5. Always return `200 OK` to Monnify regardless of processing outcome (Monnify retries on non-200)

**Background Threading:** The webhook handler spawns a `threading.Thread` to run reconciliation asynchronously. This prevents the 15-second Monnify webhook timeout from being hit during PDF generation or email sending.

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/transactions/` | Paginated transaction list (landlord's) |
| POST | `/api/transactions/monnify-webhook/` | Monnify webhook (public) |

---

## App: Bookings

### Purpose

Short-term property booking management (hotel-style stays). Tracks check-in/check-out, nightly rates, caution fees, and payment status.

### Model: `Booking`

| Field | Type | Notes |
|-------|------|-------|
| `booking_reference` | CharField | Auto-generated `BK` + 8-char hex, unique |
| `rental_property` | FK → properties | |
| `landlord` | FK → User | |
| `guest_name`, `guest_email`, `guest_phone` | CharField | |
| `check_in_date`, `check_out_date` | DateField | |
| `total_nights` | IntegerField | Auto-calculated in `save()` |
| `nightly_rate` | DecimalField | |
| `total_amount` | DecimalField | `nightly_rate × total_nights` |
| `caution_fee` | DecimalField | |
| `amount_paid` | DecimalField | |
| `balance` | DecimalField | `total_amount + caution_fee - amount_paid` |
| `status` | CharField | `pending`, `confirmed`, `checked_in`, `checked_out`, `cancelled` |
| `invoice` | FK → Invoice (nullable) | Auto-generated on booking creation |
| `source` | CharField | `direct`, `airbnb`, `booking_com`, `other` |
| `special_requests` | TextField | Optional guest requests |
| `notes` | TextField | |

The `save()` method auto-calculates `total_nights`, `total_amount`, and `balance` on every save.

### Lifecycle Automation (APScheduler Engine)

The system runs a background management command (`update_booking_statuses.py`) every 1 hour to automate the booking lifecycle:
1. **Ghost-Lock Protection**: Auto-cancels any `pending` booking that has remained unpaid/unapproved for > 24 hours, freeing up the calendar.
2. **Auto Check-in**: Transitions `confirmed` bookings to `checked_in` when the arrival date is reached.
3. **Auto Check-out**: Transitions `checked_in` bookings to `checked_out` when the departure date has passed.

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/bookings/` | List bookings |
| GET | `/api/bookings/<id>/` | Booking detail |
| POST | `/api/bookings/` | Create booking |
| POST | `/api/bookings/public/request/` | Unauthenticated endpoint for marketplace guests to request a stay |
| POST | `/api/bookings/<id>/approve/` | Approve a pending booking and email invoice to guest |
| POST | `/api/bookings/<id>/reject/` | Decline a pending booking |
| PATCH | `/api/bookings/<id>/` | Update booking |
| PATCH | `/api/bookings/<id>/status/` | Update status only |
| POST | `/api/bookings/<id>/send-payment-email/` | Re-send payment link |
| GET | `/api/bookings/property/<id>/` | All bookings for a property |

---

## App: Maintenance

### Purpose

Tracks maintenance requests submitted by tenants or landlords for properties under active leases.

### Model: `MaintenanceRequest`

| Field | Type | Notes |
|-------|------|-------|
| `title` | CharField | Brief description |
| `description` | TextField | Full details |
| `status` | CharField | `open`, `in_progress`, `resolved`, `closed` |
| `priority` | CharField | `low`, `medium`, `high`, `urgent` |
| `rental_property` | FK → properties | |
| `landlord` | FK → User | |
| `reported_by_name` | CharField | |
| `reported_by_email` | EmailField | |
| `assigned_to` | CharField | Contractor/handyman name |
| `estimated_cost` | DecimalField | |
| `actual_cost` | DecimalField | |
| `scheduled_date` | DateField | |
| `resolved_at` | DateTimeField | |
| `images` | JSONField | Array of Cloudinary URLs |
| `created_at`, `updated_at` | DateTimeField | |

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/maintenance/` | List requests |
| GET | `/api/maintenance/<id>/` | Request detail |
| POST | `/api/maintenance/` | Create request |
| PATCH | `/api/maintenance/<id>/` | Update request |
| PATCH | `/api/maintenance/<id>/status/` | Status update only |
| DELETE | `/api/maintenance/<id>/` | Delete request |
| GET | `/api/maintenance/stats/` | Counts by status/priority |

---

## App: Notifications

### Purpose

Manages in-app notifications and Web Push subscriptions (VAPID protocol).

### Models

#### `Notification`

| Field | Type | Notes |
|-------|------|-------|
| `user` | FK → User | Recipient |
| `title` | CharField | |
| `body` | TextField | |
| `notification_type` | CharField | `lease`, `payment`, `maintenance`, `general` |
| `url` | CharField | Deep link for click action |
| `is_read` | BooleanField | |
| `created_at` | DateTimeField | |

#### `PushSubscription`

| Field | Type | Notes |
|-------|------|-------|
| `user` | FK → User | |
| `endpoint` | TextField | Browser push endpoint URL |
| `p256dh` | TextField | Public key |
| `auth` | TextField | Auth secret |
| `created_at` | DateTimeField | |

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/notifications/` | List all notifications for current user |
| PATCH | `/api/notifications/<id>/read/` | Mark single notification as read |
| POST | `/api/notifications/read-all/` | Mark all as read |
| POST | `/api/notifications/subscribe/` | Register push subscription |
| POST | `/api/notifications/unsubscribe/` | Remove push subscription |

### Push Notification Dispatch

The `send_push_notification(user, title, body, url, notification_type)` utility in `utils/push_notifications.py`:

1. Creates a `Notification` database record
2. Fetches all `PushSubscription` records for that user
3. Sends Web Push messages using VAPID keys from settings
4. Handles `WebPushException` gracefully (removes stale subscriptions)

Push notifications are sent from:
- Lease approval (to tenant)
- Lease rejection (to tenant)
- Payment received (to landlord)
- Payment successful (to tenant)
- New rental application submitted — `PublicRentInitiationView` notifies the landlord immediately after email dispatch
- Rent reminder — `send_rent_reminders` management command sends a push notification to the tenant 3 days before a payment is due (alongside a reminder email)

---

## App: Admin / HQ

### Purpose

Superadmin dashboard API (`/api/padvault-hq/`). Restricted to users with `role='admin'`. Provides platform-wide visibility and control across three permission tiers.

### Admin Permission Levels

| Level | Constant | Capabilities |
|-------|----------|-------------|
| `support` | `IsSupportOrHigher` | Read-only access to users, properties, leases, maintenance, support messages, KYC. Can reply to support messages and approve KYC. |
| `moderator` | `IsModeratorOrHigher` | Everything above plus: toggle user active status, notify users, bulk suspend/activate users, publish/unpublish/flag/unflag properties, bulk publish/unpublish properties. |
| `super_admin` | `IsSuperAdmin` | Everything above plus: create/delete admins, override subscriptions, impersonate users, view transactions, view/override invoices, CSV export, broadcast notifications, manage platform config (subscription price), view system audit logs. |

### Models

#### `AdminAuditLog`

Every admin action is logged with the admin's identity, the action name, the affected object type and ID, an optional details string, and the request IP address. The last 100 entries are surfaced in the HQ audit log view.

#### `SystemConfig`

Key/value store for platform-level settings. Currently used for:

| Key | Default | Description |
|-----|---------|-------------|
| `subscription_price` | `15000` | Monthly subscription fee in NGN; used by `AdminStatsView` to compute MRR dynamically |

Seeded via `python manage.py shell -c "from Admin.models import SystemConfig; SystemConfig.objects.get_or_create(key='subscription_price', defaults={'value': '15000'})"`.

### Models (Users app — related)

#### `SupportMessageReply`

Admin replies to support messages. Stored separately from the message itself so a thread of replies can accumulate.

| Field | Type | Notes |
|-------|------|-------|
| `support_message` | FK → SupportMessage | Parent message |
| `admin` | FK → User (nullable) | Admin who replied |
| `body` | TextField | Reply content |
| `sent_at` | DateTimeField | Auto-set on creation |

On creation, if the parent message's status is `new`, it is automatically advanced to `in_progress`. A Brevo email is sent to the original sender via `EmailManager.send_support_reply_email()`.

### Endpoints

#### Auth
| Method | Path | Permission | Description |
|--------|------|------------|-------------|
| POST | `/login/` | Public | Admin login — sets `padvault_token` cookie |

#### Reporting
| Method | Path | Permission | Description |
|--------|------|------------|-------------|
| GET | `/stats/` | Support+ | Platform KPIs — users, properties, leases, MRR (dynamic from SystemConfig) |
| GET | `/system-logs/` | Super Admin | Last 100 audit log entries |
| GET | `/support-messages/` | Support+ | All support messages with reply threads |
| PATCH | `/support-messages/<id>/` | Support+ | Update message status |
| POST | `/support-messages/<id>/reply/` | Support+ | Post a reply; sends email to user |

#### Admin & User Management
| Method | Path | Permission | Description |
|--------|------|------------|-------------|
| POST | `/create-admin/` | Super Admin | Create admin account with assigned level |
| DELETE | `/delete-admin/<id>/` | Super Admin | Delete admin (cannot delete self) |
| GET | `/users/` | Support+ | All users; filterable by `role`, `status` |
| PATCH | `/users/<id>/status/` | Moderator+ | Activate/deactivate; invalidates tokens on suspend |
| PATCH | `/users/<id>/subscription/` | Super Admin | Override subscription tier/status |
| POST | `/users/<id>/impersonate/` | Moderator+ | Sets `padvault_impersonation_token` cookie |
| POST | `/stop-impersonating/` | Public | Clears impersonation cookie |
| GET | `/users/<id>/profile/` | Support+ | Full user profile — properties, leases, transactions, support messages |
| POST | `/users/<id>/notify/` | Moderator+ | Create in-app notification; optional Brevo email |
| POST | `/users/bulk-action/` | Moderator+ | Suspend or activate multiple users by ID list |

#### KYC
| Method | Path | Permission | Description |
|--------|------|------------|-------------|
| GET | `/kyc/` | Support+ | Users with `registration_step='kyc'` |
| PATCH | `/kyc/<id>/override/` | Support+ | Manually set `registration_step='complete'` |

#### Properties
| Method | Path | Permission | Description |
|--------|------|------------|-------------|
| GET | `/properties/` | Support+ | All properties with `is_flagged`, `flag_reason` |
| PATCH | `/properties/<id>/moderation/` | Moderator+ | Actions: `publish`, `unpublish`, `flag` (with optional reason), `unflag` |
| POST | `/properties/bulk-action/` | Moderator+ | `publish` or `unpublish` multiple properties |

#### Operations
| Method | Path | Permission | Description |
|--------|------|------------|-------------|
| GET | `/leases/` | Support+ | All lease initiations |
| GET | `/maintenance/` | Support+ | All maintenance requests |

#### Financial (Super Admin only)
| Method | Path | Permission | Description |
|--------|------|------------|-------------|
| GET | `/transactions/` | Super Admin | Full platform transaction ledger |
| GET | `/invoices/` | Super Admin | All invoices platform-wide |
| PATCH | `/invoices/<id>/override/` | Super Admin | Force-set invoice status; sets `paid_at` if status=`paid` |
| GET | `/export/?type=<type>` | Super Admin | Streaming CSV download; `type`: `users`, `transactions`, `leases` |

#### Broadcast & Config (Super Admin only)
| Method | Path | Permission | Description |
|--------|------|------------|-------------|
| POST | `/broadcast/` | Super Admin | `bulk_create` notifications for segment (`all`, `landlords`, `tenants`, `premium`); optional Brevo email loop |
| GET | `/config/` | Super Admin | Returns all `SystemConfig` key/value pairs |
| PATCH | `/config/` | Super Admin | `update_or_create` a config entry; logged in audit trail |

---

## Utilities

### reconciliation.py — Payment Reconciliation Engine

`reconcile_payment(invoice, amount_paid, gateway_reference="MANUAL")`

The single source of truth for what happens when a payment is confirmed. Called from:
- `InvoiceMarkPaidView.patch()` (manual)
- `PublicInvoiceVerifyPaymentView.post()` (Monnify verify endpoint)
- Monnify webhook background thread

**Execution (all inside `transaction.atomic()`):**

1. **Row lock:** Re-fetches `invoice` with `select_for_update()` to serialize concurrent calls
2. **Idempotency check:** Returns `True` immediately if `invoice.status == 'paid'` or a success transaction already exists for the invoice number
3. **Invoice status:** Sets to `'partial'` if underpayment, `'paid'` with `paid_at` timestamp if full/overpayment
4. **Transaction record:** Creates or updates a `Transaction` row with `status='success'`, `payment_gateway`, `gateway_reference`, `completed_at`
5. **Rent handling (if `invoice.rent` is set):**
   - Finds the linked `PaymentSchedule` entry (or falls back to earliest unpaid)
   - Updates schedule entry: `amount_paid`, `status` (`paid` or `partial`), `paid_at`
   - Updates `Rent.amount_paid`, recalculates `balance`
   - Syncs property status to `'occupied'` if not already
   - Cascades: auto-generates the next unpaid installment's invoice
6. **Booking handling (if `invoice.booking` is set):**
   - Updates `booking.amount_paid`, `balance`
   - Sets `booking.status = 'confirmed'` if fully paid
7. **Subscription handling (if `invoice.notes == 'Premium Subscription Renewal'`):**
   - Sets `user.subscription_tier = 'premium'`, `subscription_status = 'active'`
   - Extends or creates `subscription_expires_at` (+30 days)
   - Sends subscription confirmation email
8. **Notifications:**
   - Sends payment receipt email to tenant
   - Sends payment notification email to landlord
   - Sends push notification to both parties

### email.py — Brevo Email Manager

`EmailManager` class with static methods. All emails send via Brevo HTTP API (`https://api.brevo.com/v3/smtp/email`), not Django's SMTP backend.

Available send methods:

| Method | Trigger |
|--------|---------|
| `send_otp_email(user, otp)` | Registration OTP |
| `send_new_initiation_notification(landlord, initiation)` | Landlord notified of new application |
| `send_application_confirmation_email(initiation)` | Applicant confirmation on submission |
| `send_lease_signature_email(rent, tenant_email, ...)` | Tenant signing link |
| `send_final_lease_document(rent, tenant_email, landlord_email, document_url)` | Post-signing PDF link |
| `send_payment_receipt_email(transaction, invoice, tenant_email, tenant_name)` | Payment receipt |
| `send_landlord_payment_notification(transaction, landlord)` | Landlord payment alert |
| `send_subscription_confirmation(user, plan_name)` | Premium subscription confirmed |
| `send_rent_reminder_email(tenant_email, tenant_name, property_title, amount_due, due_date)` | Rent due in 3 days (called by `send_rent_reminders` management command) |
| `send_forgot_password_email(user, reset_url)` | Password reset link |
| `send_contact_confirmation_email(name, email)` | Contact form auto-reply |
| `send_support_reply_email(recipient_email, recipient_name, subject, reply_body, original_message)` | Admin reply to support ticket |
| `send_admin_notification_email(recipient_email, recipient_name, title, message)` | Admin-initiated direct notification to a user |

All methods call the internal `_send_email(subject, template_name, context, recipient_list)` which:
1. Reads `settings.BREVO_API_KEY`
2. Renders the HTML template from `templates/emails/`
3. POSTs to Brevo API with 10-second timeout
4. Logs success/failure; exceptions are swallowed and logged (email failures are non-fatal)

### monnify.py — MonnifyProvider

Handles all communication with Monnify API:

| Method | Description |
|--------|-------------|
| `get_access_token()` | OAuth2 client_credentials, cached |
| `initialize_transaction(amount, reference, description, ...)` | Create payment session |
| `verify_transaction(reference)` | Query transaction status |
| `create_subaccount(landlord)` | Create Monnify subaccount for split payments |

**Split Payments:** When a landlord has a `monnify_subaccount_code`, payments are split between Padvault (platform fee) and the landlord's subaccount.

**Webhook Security:** `HMAC-SHA512(request_body, MONNIFY_SECRET_KEY)` compared against `monnifySignature` header.

### push_notifications.py

`send_push_notification(user, title, body, url, notification_type='general')`

1. Creates `Notification` DB record
2. Fetches `PushSubscription` records for user
3. Sends via Web Push with VAPID signing (`settings.VAPID_PRIVATE_KEY`, `settings.VAPID_CLAIMS`)
4. Removes stale subscriptions on `WebPushException`

### rate_limit.py

`@rate_limit(limit, window_seconds, key_prefix)` decorator for class-based views via `@method_decorator`.

Uses an in-memory dictionary keyed by `f"{key_prefix}:{client_ip}"`. Returns `429 Too Many Requests` when exceeded.

### calendar.py

`check_booking_conflict(property_id, start_date, end_date)`

Checks `Rent` and `Booking` tables for overlapping date ranges on the given property. Returns a conflict description string if overlap found, `None` if clear. Used in the lease approval flow.

---

## Payment System — Monnify

### Overview

Monnify is the Nigerian payment gateway used for all online payments. The integration uses the **Checkout SDK** (hosted payment page) rather than inline or card-form payments.

### Complete Payment Flow

```
Tenant clicks "Proceed to Payment"
         ↓
POST /api/invoices/public/<id>/init-payment/
  → MonnifyProvider.initialize_transaction()
  → Returns { checkoutUrl }
  → Saves monnify_reference to invoice
         ↓
window.location.href = checkoutUrl
  (Tenant redirected to Monnify-hosted payment page)
         ↓
Tenant completes payment on Monnify
         ↓
         ├── Monnify webhook fires: POST /api/transactions/monnify-webhook/
         │     → Signature verified
         │     → Background thread: reconcile_payment()
         │
         └── Tenant redirected back to /pay/<publicId>
               → PaymentPortal auto-calls verify-payment
               → POST /api/invoices/public/<id>/verify-payment/
                     → MonnifyProvider.verify_transaction()
                     → reconcile_payment() (idempotent — no-ops if webhook already ran)
```

### Idempotency

`reconcile_payment()` uses `select_for_update()` inside `transaction.atomic()` plus an early-exit check. Whether the webhook or the verify-payment endpoint runs first, the second call is a no-op. No double-credit is possible.

---

## Storage — Cloudinary

### Resource Types

| Content | `resource_type` | URL Pattern |
|---------|-----------------|-------------|
| Profile pictures | `image` | `/image/upload/...` |
| Property images | `image` | `/image/upload/...` |
| Lease PDFs | `raw` | `/raw/upload/...` |

**Why `raw` for PDFs:** Cloudinary's image CDN enforces "Restrict PDF and ZIP file delivery" by default — PDFs uploaded as `resource_type="image"` return 403 on delivery. Raw resources are served as opaque binary blobs without this restriction.

### Folders

| Folder | Contents |
|--------|---------|
| `padvault/leases/` | Signed lease PDFs, named `lease_<uuid>.pdf` |
| `padvault/properties/` | Property images |
| `padvault/profiles/` | Profile pictures |

### Proxy Pattern

Lease PDFs are **never served as direct Cloudinary URLs** to end users. The frontend always requests them through the Django proxy at `/api/rent/documents/<uuid>/view/`, which:
1. Looks up `rent.lease_document_url`
2. Fetches the Cloudinary raw URL with `requests.get()`
3. Streams the response bytes back to the browser as `application/pdf`

The email template (`lease_final_document.html`) also links to the proxy URL (`https://padvault.io/documents/view/<uuid>`), not the Cloudinary URL directly.

---

## Email System — Brevo

Templates are HTML files in `rent_core_service/templates/emails/`. All templates receive a `context` dict rendered with Django's template engine.

| Template | Purpose |
|----------|---------|
| `otp_verification.html` | Registration OTP |
| `landlord_new_application.html` | Landlord — new rental application notification |
| `application_confirmation.html` | Applicant — submission received confirmation |
| `lease_signature.html` | Tenant — e-sign invitation |
| `lease_final_document.html` | Both parties — signed lease PDF link |
| `payment_receipt.html` | Tenant — payment receipt |
| `landlord_notification.html` | Landlord — payment received |
| `subscription_confirmation.html` | User — premium activated |
| `rent_reminder.html` | Tenant — rent due in 3 days (property, amount, due date) |
| `password_reset_otp.html` | Password reset OTP |
| `contact_us_admin.html` | Internal — contact form submission forwarded to admin |
| `lease_document.html` | The actual PDF content rendered to HTML before xhtml2pdf conversion |

---

## PDF Generation

Used in `PublicLeaseSignView.post()`:

```python
from xhtml2pdf import pisa
from io import BytesIO
from django.template.loader import render_to_string

html_string = render_to_string('emails/lease_document.html', context)
pdf_file = BytesIO()
pisa_status = pisa.CreatePDF(src=html_string, dest=pdf_file, encoding='utf-8')

if pisa_status.err or pdf_file.getbuffer().nbytes < 100:
    return Response({"error": "Empty PDF"}, status=500)

pdf_file.seek(0)
upload_result = cloudinary.uploader.upload(
    pdf_file,
    resource_type="raw",
    type="upload",
    folder="padvault/leases",
    public_id=f"lease_{rent.lease_public_id}.pdf",
    overwrite=True
)
```

The `lease_document.html` template renders the full lease agreement with both parties' signatures embedded as base64 PNG `<img>` tags.

---

## Complete API Reference

### Users (`/api/users/`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/register/` | Public | Create account |
| POST | `/verify-email/` | Public | Verify OTP |
| POST | `/resend-otp/` | Public | Resend OTP |
| POST | `/login/` | Public | Login, set JWT cookie |
| POST | `/logout/` | JWT | Clear JWT cookie |
| POST | `/logout/all/` | JWT | Invalidate all sessions |
| GET | `/profile/` | JWT | Get profile |
| PUT | `/profile/update/` | JWT | Update profile |
| POST | `/profile/picture/` | JWT | Upload profile picture |
| POST | `/change-password/` | JWT | Change password |
| DELETE | `/profile/delete/` | JWT | Delete account |
| POST | `/forgot-password/` | Public | Send reset link |
| POST | `/reset-password/` | Public | Apply new password |
| POST | `/kyc-verify/` | JWT | Submit KYC |
| POST | `/subscribe/` | JWT | Initiate premium subscription |
| POST | `/verify-subscription/` | JWT | Verify Monnify payment and activate premium |
| POST | `/contact/` | Public | Submit contact message |

### Properties (`/api/properties/`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/` | Public | Marketplace list |
| GET | `/meta/` | Public | Filter metadata |
| GET | `/featured/` | Public | Featured listings |
| GET | `/categories/` | Public | Type counts |
| GET | `/status-counts/` | Public | Status counts |
| GET | `/<id>/view/` | Public | Property detail |
| GET | `/<id>/availability/` | Public | Availability check |
| GET | `/landlord/properties/` | JWT | Own properties |
| GET | `/landlord/<id>/` | JWT | Own property detail |
| POST | `/landlord/create/` | JWT | Create property |
| PATCH | `/landlord/<id>/` | JWT | Update property |
| PATCH | `/landlord/<id>/status/` | JWT | Update status |
| DELETE | `/landlord/<id>/` | JWT | Delete property |
| POST | `/<id>/images/upload/` | JWT | Upload image |
| DELETE | `/<id>/images/remove/` | JWT | Remove image |
| GET/POST | `/<id>/assets/` | JWT | List/create assets |
| PUT/DELETE | `/<id>/assets/<assetId>/` | JWT | Update/delete asset |

### Rent (`/api/rent/`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/` | JWT | List leases |
| GET | `/<id>/` | JWT | Lease detail |
| PATCH | `/<id>/` | JWT | Update lease |
| PATCH | `/<id>/cancel/` | JWT | Cancel lease |
| GET | `/<id>/schedule/` | JWT | Payment schedule |
| GET/POST | `/<id>/payments/` | JWT | Payments list/create |
| POST | `/schedule/<id>/send-payment-email/` | JWT | Resend email |
| GET/POST | `/initiations/` | JWT | List/create initiations |
| PATCH | `/initiations/<id>/approve/` | JWT | Approve |
| PATCH | `/initiations/<id>/reject/` | JWT | Reject |
| POST | `/initiations/public/` | Public | Anonymous application |
| GET | `/lease/<uuid>/` | Public | Public lease view |
| POST | `/lease/<uuid>/sign/` | Public | Sign lease |
| GET | `/documents/<uuid>/view/` | Public | PDF proxy |

### Invoices (`/api/invoices/`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET/POST | `/` | JWT | List/create |
| GET | `/<id>/` | JWT | Detail |
| PATCH | `/<id>/mark-paid/` | JWT | Manual mark paid |
| GET | `/public/<public_id>/` | Public | Payment portal view |
| POST | `/public/<public_id>/init-payment/` | Public | Init Monnify |
| POST | `/public/<public_id>/verify-payment/` | Public | Verify & reconcile |

### Transactions (`/api/transactions/`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/` | JWT | Transaction list |
| POST | `/monnify-webhook/` | Public | Monnify webhook |

### Bookings (`/api/bookings/`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET/POST | `/` | JWT | List/create |
| GET/PATCH | `/<id>/` | JWT | Detail/update |
| PATCH | `/<id>/status/` | JWT | Status update |
| POST | `/<id>/send-payment-email/` | JWT | Resend payment link |
| GET | `/property/<id>/` | JWT | Property's bookings |

### Maintenance (`/api/maintenance/`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET/POST | `/` | JWT | List/create |
| GET/PATCH | `/<id>/` | JWT | Detail/update |
| PATCH | `/<id>/status/` | JWT | Status update |
| DELETE | `/<id>/` | JWT | Delete |
| GET | `/stats/` | JWT | Stats by status/priority |

### Notifications (`/api/notifications/`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/` | JWT | All notifications |
| PATCH | `/<id>/read/` | JWT | Mark read |
| POST | `/read-all/` | JWT | Mark all read |
| POST | `/subscribe/` | JWT | Register push subscription |
| POST | `/unsubscribe/` | JWT | Remove push subscription |

### Admin / HQ (`/api/padvault-hq/`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/login/` | Public | Admin login |
| GET | `/stats/` | Support+ | Platform stats (MRR dynamic) |
| GET | `/system-logs/` | Super Admin | Audit log (last 100) |
| GET | `/support-messages/` | Support+ | Support inbox with reply threads |
| PATCH | `/support-messages/<id>/` | Support+ | Update message status |
| POST | `/support-messages/<id>/reply/` | Support+ | Reply to message + send email |
| POST | `/create-admin/` | Super Admin | Create admin account |
| DELETE | `/delete-admin/<id>/` | Super Admin | Remove admin |
| GET | `/users/` | Support+ | All users |
| PATCH | `/users/<id>/status/` | Moderator+ | Toggle active + invalidate tokens |
| PATCH | `/users/<id>/subscription/` | Super Admin | Override subscription |
| POST | `/users/<id>/impersonate/` | Moderator+ | Start impersonation |
| POST | `/stop-impersonating/` | Public | End impersonation |
| GET | `/users/<id>/profile/` | Support+ | Full profile aggregation |
| POST | `/users/<id>/notify/` | Moderator+ | In-app notification + optional email |
| POST | `/users/bulk-action/` | Moderator+ | Bulk suspend/activate |
| GET | `/kyc/` | Support+ | Pending KYC queue |
| PATCH | `/kyc/<id>/override/` | Support+ | Manual KYC approval |
| GET | `/properties/` | Support+ | All properties with flag state |
| PATCH | `/properties/<id>/moderation/` | Moderator+ | publish/unpublish/flag/unflag |
| POST | `/properties/bulk-action/` | Moderator+ | Bulk publish/unpublish |
| GET | `/leases/` | Support+ | All lease initiations |
| GET | `/maintenance/` | Support+ | All maintenance requests |
| GET | `/transactions/` | Super Admin | Full transaction ledger |
| GET | `/invoices/` | Super Admin | All platform invoices |
| PATCH | `/invoices/<id>/override/` | Super Admin | Force invoice status |
| GET | `/export/?type=` | Super Admin | Streaming CSV (users/transactions/leases) |
| POST | `/broadcast/` | Super Admin | Bulk notify segment + optional email |
| GET/PATCH | `/config/` | Super Admin | Read/update SystemConfig |
