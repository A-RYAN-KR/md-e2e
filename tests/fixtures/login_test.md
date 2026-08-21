# Login Test Suite @smoke @regression

This suite verifies the end-to-end login flow for the application.

```python setup
BASE_URL = "https://staging.example.com"
```

## Successful Login @happy-path

The user should be able to log in with valid credentials and be redirected
to the dashboard.

- Navigate to "https://staging.example.com/login"
- Fill "Email" with "{{admin_email}}"
- Fill "Password" with "${admin_password}"
- Click button "Sign In"
- Assert heading "Dashboard" is visible
- Assert URL contains "/dashboard"

## Failed Login — Invalid Password @negative

When the user enters an incorrect password, an error message should appear.

- Navigate to "https://staging.example.com/login"
- Fill "Email" with "user@example.com"
- Fill "Password" with "wrong-password"
- Click button "Sign In"
- Assert text "Invalid credentials" is visible
- Assert URL is "https://staging.example.com/login"

```python teardown
# Clean up test user session
```

## Parameterised Login @data-driven

Verify login with multiple credential sets.

| username          | password   | expected_page |
|-------------------|------------|---------------|
| admin@test.com    | admin123   | /dashboard    |
| editor@test.com   | editor456  | /editor       |

- Navigate to "https://staging.example.com/login"
- Fill "Email" with "{{username}}"
- Fill "Password" with "{{password}}"
- Click button "Sign In"
- Assert URL contains "{{expected_page}}"
