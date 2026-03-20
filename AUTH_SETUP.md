# Streamlit Authenticator Setup Guide

## Overview

Authentication is now enabled by default on all pages. Admin-only pages require the "admin" role.

## Admin-Only Pages

These pages require `required_roles: ['admin']`:

- **Python Terminal Interactive** — arbitrary Python code execution
- **USB Serial Console** — hardware device access
- **PDF Sign** — digital certificate/signature operations
- **Dynamic JSON Canvas** — complex dynamic UI rendering
- **Streamlit App Maker** — app source code generation and publishing

Regular authenticated users can access all other pages.

## Configuration

### Step 1: Generate a Cookie Key

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Copy the output. You'll use this as `STREAMLIT_AUTH_COOKIE_KEY`.

### Step 2: Create User Credentials (JSON)

Option A: Via environment variable or Streamlit secrets, set `STREAMLIT_AUTH_USERS_JSON` with a JSON array:

```json
[
  {
    "username": "admin_user",
    "name": "Admin User",
    "password": "hashed_password_here",
    "roles": ["admin"],
    "email": "admin@example.com"
  },
  {
    "username": "regular_user",
    "name": "Regular User",
    "password": "hashed_password_here",
    "roles": [],
    "email": "user@example.com"
  }
]
```

Option B: Alternatively, use `STREAMLIT_AUTH_CREDENTIALS_JSON` with the full streamlit-authenticator credentials structure:

```json
{
  "usernames": {
    "admin_user": {
      "name": "Admin User",
      "password": "hashed_password_here",
      "roles": ["admin"]
    },
    "regular_user": {
      "name": "Regular User",
      "password": "hashed_password_here"
    }
  }
}
```

### Step 3: Hash Passwords

Password values must be **hashed**, not plain text. Use streamlit-authenticator's hasher:

```python
from streamlit_authenticator import Authenticate
print(Authenticate.hashed_passwords(["my_password"]))
```

This will output something like: `['$2b$12$...(bcrypt hash)...']`

Use that hash value in your credentials.

### Step 4: Configure Heroku Config Vars

Set these via Heroku CLI or the dashboard:

```bash
heroku config:set \
  STREAMLIT_AUTH_COOKIE_KEY="<your_cookie_key>" \
  STREAMLIT_AUTH_USERS_JSON='<your_json_array>'
```

Or in Streamlit secrets (local `.streamlit/secrets.toml`):

```toml
STREAMLIT_AUTH_COOKIE_KEY = "your_cookie_key_here"
STREAMLIT_AUTH_USERS_JSON = '[{"username": "admin_user", "name": "Admin", "password": "hashed_pwd", "roles": ["admin"]}]'
```

### Step 5: (Optional) Disable Auth for Development

To run without authentication locally (dev/testing only):

```bash
export STREAMLIT_AUTH_ENABLED=false
streamlit run deploy/heroku/main.py
```

**Never** disable auth in production.

### Step 6: (Optional) Show Source Code

Source code display is disabled by default for security. To enable it:

```bash
export STREAMLIT_SHOW_SOURCE_CODE=true
```

## Login Flow

1. User navigates to the app.
2. Login form appears in the main area.
3. User enters username/password.
4. On success, user is logged in and session cookie is set.
5. Sidebar shows signed-in username + Logout button.
6. User can navigate between pages based on their role.
7. Clicking Logout clears the session.

## Role Enforcement

The auth guard checks user roles against required roles:

```python
require_authentication("Page Name", required_roles=['admin'])
```

If the user does not have at least one of the required roles, they see an error and are offered logout.

## Troubleshooting

### "Authentication setup error: ..."

- Check that `STREAMLIT_AUTH_COOKIE_KEY` is set.
- Check that either `STREAMLIT_AUTH_CREDENTIALS_JSON` or `STREAMLIT_AUTH_USERS_JSON` is set and valid JSON.
- Check the logs for exact error message.

### Login always fails

- Ensure passwords are hashed, not plaintext.
- Verify the hasher used matches streamlit-authenticator expectations (bcrypt).
- Check browser cookies are not blocked.

### User is logged in but page says "you do not have access"

- The user's roles do not include the required role. 
- Check your user record includes `"roles": ["admin"]` if the page requires admin access.

## Security Notes

- Passwords stored in cleartext in config vars are a risk. Use Streamlit secrets or a secure secrets manager.
- Cookie key should be strong and random (use the hasher step above).
- If compromised, regenerate the cookie key and ask users to log in again.
- Auth is application-level only. Use network-level controls (reverse proxy, WAF, etc.) for production.

## Example: Quick Local Test

```bash
export STREAMLIT_AUTH_COOKIE_KEY="test_key_12345"
export STREAMLIT_AUTH_USERS_JSON='[{"username": "test", "name": "Test User", "password": "$2b$12$test_hash_here", "roles": ["admin"]}]'
streamlit run deploy/heroku/main.py
```

Then log in with username `test` and the plaintext password you hashed.
