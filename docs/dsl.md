# Markdown DSL Reference

md-e2e executes test specs written in a simple, structured Markdown format.

## Suite Definition
A suite starts with a single `# Heading 1`. You can attach tags using `@tag` syntax.

```markdown
# Auth & Login Suite @smoke @auth
```

## Scenario Definition
Each scenario starts with a `## Heading 2`.

```markdown
## Successful Login Scenario @user-flow
```

## Step Syntax
Steps are written as bulleted list items (`-` or `*`). The framework parses actions using a natural English vocabulary.

### Supported Actions

#### Navigation
- `Navigate to "https://example.com"`
- `Reload page`

#### Interaction
- `Click button "Sign In"`
- `Click link "Forgot Password?"`
- `Fill input "Email" with "user@example.com"`
- `Select "Canada" from "Country"`
- `Check checkbox "Accept Terms"`
- `Uncheck checkbox "Receive Newsletter"`
- `Hover over "User Menu"`
- `Press "Enter"`

#### Assertions
- `Assert heading "Dashboard" is visible`
- `Assert button "Delete" is hidden`
- `Assert URL contains "/dashboard"`
- `Assert title is "My Application"`
- `Assert input "Email" value is "user@example.com"`

#### State Store
- `Store text from heading "Order Total" as "TOTAL_PRICE"`
- `Fill input "Amount" with "{{TOTAL_PRICE}}"`
