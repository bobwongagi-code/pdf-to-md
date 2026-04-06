# Security Policy

This repository works with external API credentials. Treat those credentials as sensitive.

## Supported Scope

This policy applies to:

- repository source code
- release artifacts
- documentation and examples
- operational guidance around API credentials

## What Counts as Sensitive

Do not publish any of the following in issues, pull requests, comments, logs, screenshots, or examples:

- `PADDLEOCR_ACCESS_TOKEN`
- real `PADDLEOCR_DOC_PARSING_API_URL` values tied to your private environment
- raw output that contains secrets, internal URLs, or customer data
- shell history or config snippets that include live credentials

Use placeholders such as:

```bash
export PADDLEOCR_DOC_PARSING_API_URL="https://your-endpoint/layout-parsing"
export PADDLEOCR_ACCESS_TOKEN="your-token"
```

## If You Think a Credential Was Exposed

Do this in order:

1. Rotate the token immediately in the PaddleOCR console.
2. Replace the token anywhere it is stored locally.
3. Check shell config files, scripts, screenshots, logs, and chat history.
4. If the secret entered git history, rewrite history before treating the repo as clean.
5. Open a sanitized issue only after the live secret has been rotated.

## Reporting Security Problems

For non-sensitive bugs, open a normal GitHub issue.

For anything involving credentials, private endpoints, or customer documents:

- do not open a public issue with the raw details
- sanitize the report first
- if private coordination is needed, contact the repository owner through GitHub before sharing sensitive material

## Hard Rules for Contributors

- Never commit real tokens.
- Never commit `.env` files with live values.
- Never replace placeholders in docs with real credentials.
- Never paste full provider responses if they may contain secrets or private document content.

## Good Practice

- Prefer environment variables over hard-coded credentials.
- Use separate tokens for testing and production when possible.
- Rotate tokens that were ever shared outside your local machine.
- Review diffs before pushing.
- Treat chat transcripts as potentially sensitive if they include live secrets.

## Repository Status

At the time this file was added, the repository was checked for known live PaddleOCR token and endpoint leakage and only placeholder values were kept in tracked files.
