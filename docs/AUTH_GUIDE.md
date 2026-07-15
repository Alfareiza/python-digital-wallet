# Authentication Guide

## Overview

The Digital Wallet API uses email-based authentication with JWT bearer tokens. All authenticated endpoints require an `Authorization: Bearer <token>` header.

---

## 1. Register a New User

**Endpoint:** `POST /auth/register`

**Request:**

```json
{
  "email": "user@example.com",
  "name": "John Doe",
  "password": "secure_password_123"
}
```

**Success Response (201):**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "user@example.com",
  "name": "John Doe"
}
```

**Common Errors:**

- `400 Bad Request` — Email already registered or invalid input (check validation rules for `email` and `name` fields).
- `422 Unprocessable Entity` — Validation failed (e.g., missing fields, invalid email format).

---

## 2. Login and Obtain JWT

**Endpoint:** `POST /auth/token`

**Request (form-encoded):**

```
POST /auth/token
Content-Type: application/x-www-form-urlencoded

username=user@example.com&password=secure_password_123
```

> **Important:** The `username` field must be the **email address**, not a separate username field.

**Success Response (200):**

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

**Common Errors:**

- `401 Unauthorized` — Incorrect email or password.

---

## 3. Use the Token for Protected Endpoints

Include the token in the `Authorization` header for any authenticated request:

```
GET /wallet
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

**Token Expiration:** Tokens expire after `access_token_expire_minutes` (default: 60 minutes). When expired, re-authenticate to obtain a fresh token.

---

## Key Considerations

1. **Email is the login identifier.** Use email address in the `username` field of the login request, not a separate username.

2. **Passwords are hashed with bcrypt.** Never log, store, or transmit plain passwords. The API accepts only the plain password at registration/login and hashes it server-side.

3. **JWT tokens are short-lived.** Default expiration is 60 minutes. Implement token refresh logic on the client side (re-login when expired).

4. **Distinct error messages for debugging.**
   - `"Token has expired"` — Token is valid but past its expiration time.
   - `"User not found"` — Token is valid but the user no longer exists in the database.
   - `"Could not validate credentials"` — Token is malformed or cryptographically invalid.
   - `"Incorrect email or password"` — Login credentials do not match.

5. **Bearer token format.** Always use `Authorization: Bearer <token>`, not `Bearer: <token>` or other variations.

---

## Example Workflow (cURL)

```bash
# 1. Register
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"dev@example.com","name":"Developer","password":"mypass123"}'

# 2. Login
TOKEN=$(curl -s -X POST http://localhost:8000/auth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=dev@example.com&password=mypass123" | jq -r '.access_token')

# 3. Use token on protected endpoints
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/wallet
```
