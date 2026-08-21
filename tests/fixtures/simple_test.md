# Simple Actions Test

## Basic Interactions

- Click "Submit"
- Click button "Save"
- Click link "Home"
- Hover over "Profile Menu"
- Hover button "Help"
- Press "Enter"
- Fill "Search" with "test query"
- Fill input "username" with "admin"
- Select "Option A" from "Dropdown"
- Upload "report.pdf" to "File Input"
- Check checkbox "Remember me"
- Uncheck "Newsletter"

## Assertion Variants

- Assert "Welcome" is visible
- Assert heading "Dashboard" is visible
- Assert button "Submit" is hidden
- Assert URL is "https://example.com"
- Assert URL contains "/dashboard"
- Assert URL matches "/users/\d+"
- Assert title is "My App"
- Assert title contains "App"
- Assert "email" value is "test@example.com"
- Assert "email" value contains "test"

## Control Steps

- Wait 3 seconds
- Wait 1 second
- Wait for network idle

## Variable Store

- Store text from heading "Welcome" as "greeting"
- Store text from "Price" as "item_price"

## Checklist Steps

- [x] Navigate to "https://example.com"
- [ ] Click button "Login"
- [x] Assert heading "Home" is visible

## Custom / Unrecognised Steps

- Do something completely custom here
- Verify the database has 5 records
