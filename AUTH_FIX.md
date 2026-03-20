# Authentication Setup & Configuration Guide

## Issue Resolution

**Error Fixed:** "Location must be one of 'main' or 'sidebar' or 'unrendered'"

This error occurred because the `_render_logout()` function was attempting to pass location parameters (`'sidebar'`, `'main'`) to `streamlit-authenticator`'s logout method, which either:
1. Doesn't support those parameters in the current version, or
2. Creates conflicts when called within existing Streamlit component contexts

**Solution:** Simplified the logout rendering to work without explicit location parameters, letting `streamlit-authenticator` handle component placement automatically.

## Quick Start

### 1. Configuration (Local Testing)

The app reads auth configuration from environment variables or Streamlit secrets. Create `.streamlit/secrets.toml`:

```toml
STREAMLIT_AUTH_COOKIE_KEY = "f8d3c7a2b9e1f4c6d2a8e5b3f1c7d9a2e6b4f1d3a9c2e8b5f7a1d4c6e9f2b5"

STREAMLIT_AUTH_USERS_JSON = '''[
  {
    "username": "admin_local",
    "name": "Admin (Local Test)",
    "password": "$2b$12$Ga6pqwsF4PV4KFlEKcrptes4QU7B8s1lFPWyhfsFoLXnptimP0Gru",
    "roles": ["admin"],
    "email": "admin@localhost"
  },
  {
    "username": "user_local",
    "name": "Regular User (Local Test)",
    "password": "$2b$12$3dbSQUtmzCwQOltztDdJ6uqzys55rTn118PxnagwcEAzcxlL/9yQ6",
    "roles": [],
    "email": "user@localhost"
  }
]'''
```

**Test Credentials:**
- Admin: `admin_local` / `password123` (has admin access)
- User: `user_local` / `password456` (regular access only)

### 2. Run the Application

```bash
# Activate venv if needed
source .venv/bin/activate

# Install requirements if not done
pip install -r requirements.txt

# Start the app
streamlit run deploy/heroku/main.py
```

The login form will appear in the main area. Log in with one of the test credentials above.

### 3. Verify Role-Based Access

After logging in:

**As admin_local:**
- ✅ Access all pages, including dangerous ones:
  - Python Terminal Interactive
  - Serial Console
  - PDF Sign
  - Dynamic Page
  - Streamlit App Maker

**As user_local:**
- ✅ Access regular pages: form builders, dashboards, tools
- ❌ Cannot access admin-only pages (will see "not authorized" error)

## Configuration Options

### Environment Variables (for production)

Set these in your deployment environment:

```bash
# Required
STREAMLIT_AUTH_COOKIE_KEY="generate_with_python3_-c_import_secrets;_print_secrets.token_hex_32"
STREAMLIT_AUTH_USERS_JSON='[{"username":"...", "password":"...", "roles":["admin"]}, ...]'

# Optional
STREAMLIT_AUTH_ENABLED="true"  # Set to "false" to disable auth entirely
STREAMLIT_AUTH_COOKIE_NAME="streamlit_auth"  # Cookie name
STREAMLIT_AUTH_COOKIE_EXPIRY_DAYS="7"  # Session expiry
```

### Streamlit Secrets File (for local dev)

Instead of environment variables, you can use `.streamlit/secrets.toml`:

```toml
STREAMLIT_AUTH_COOKIE_KEY = "..."
STREAMLIT_AUTH_USERS_JSON = '...'
STREAMLIT_AUTH_ENABLED = "true"
```

## Password Hashing

All passwords must be bcrypt-hashed. To generate password hashes:

```bash
python3 << 'EOF'
import bcrypt

passwords = [
    'my_secure_password_1',
    'my_secure_password_2',
]

for password in passwords:
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    print(f"Password: {password}")
    print(f"Hash: {hashed}\n")
EOF
```

Copy the hashes into your `STREAMLIT_AUTH_USERS_JSON` configuration.

## Cookie Key Generation

Generate a secure cookie key:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Use the output for `STREAMLIT_AUTH_COOKIE_KEY`.

## User Schema

Each user in `STREAMLIT_AUTH_USERS_JSON` must have:

```json
{
  "username": "unique_username",
  "name": "Display Name",
  "password": "bcrypt_hashed_password",
  "roles": ["role1", "role2"],
  "email": "optional@email.com"
}
```

- **username** (required): Unique identifier for login
- **name** (required): Display name shown in sidebar
- **password** (required): Bcrypt-hashed password
- **roles** (optional): List of role names (e.g., `["admin"]`). Empty list for no roles.
- **email** (optional): User's email address

## Admin-Only Pages

The following pages require `roles: ["admin"]`:

1. **python_terminal_interactive.py** — Execute arbitrary Python code
2. **serial_console.py** — Access USB/hardware devices
3. **pdf_sign.py** — Digital signatures and PKI operations
4. **dynamic_page.py** — Complex JSON schema canvas
5. **streamlit_app_maker_app.py** — App generation and publishing

All other pages are available to any authenticated user.

## Troubleshooting

### "Authentication setup error: ..."

**Check:**
1. `STREAMLIT_AUTH_COOKIE_KEY` is set and non-empty
2. `STREAMLIT_AUTH_USERS_JSON` or `STREAMLIT_AUTH_CREDENTIALS_JSON` is valid JSON
3. Environment variables are properly exported (use `.streamlit/secrets.toml` for local testing)

### Login form doesn't appear

**Solutions:**
1. Clear browser cache and reload
2. Check browser console for errors
3. Verify `.streamlit/secrets.toml` exists and has valid JSON
4. Restart the Streamlit app

### Getting "You are logged in but do not have access to this page"

This means you logged in successfully but your account doesn't have the required role. Either:
- Log out and log in as a different user with the appropriate role
- Ask an admin to add your account to the required role

## Code Changes

**Modified File:** `deploy/heroku/pages/_auth_guard.py`

Key changes:
- Removed location parameters from `_render_logout()` call attempts
- Simplified to just call `authenticator.logout("Logout")` or `authenticator.logout()`
- Changed sidebar rendering from context manager to direct `st.sidebar.caption()` call
- Added fallback chains for API version compatibility

## Files

- **Auth module:** `deploy/heroku/pages/_auth_guard.py`
- **Example secrets:** `.streamlit/secrets_example.toml`
- **Local secrets (add to .gitignore):** `.streamlit/secrets.toml`
- **Pages with auth guards:** All Python files in `deploy/heroku/pages/*.py`

## Next Steps

1. ✅ Test locally with provided test credentials
2. Generate production password hashes for real users
3. Set environment variables / secrets in your deployment platform
4. Deploy and verify auth works in production
5. Distribute login credentials to users securely
