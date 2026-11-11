# Security

## Reporting a problem

If you find a security problem in siphon, please don't open a public issue. Use the **Report a vulnerability** button on the repository's **Security** tab instead, so it can be fixed before it is announced. I'll reply as soon as I can.

## What siphon does to stay safe

- Only `http` and `https` addresses can be typed in. Local files are only read when you pick them in the file dialog.
- Downloads are limited: 20 MB per page, connection and read timeouts, and a 60-second ceiling.
- Pages nested more than 1,000 levels deep are refused, and the parser reads big pages in a time that grows steadily with their size, so a hostile page can't freeze the app.
- Website certificates are always checked.
- Saved CSV and Excel files can't run scraped text as a formula: cells that start with `=`, `@`, `+` or `-` are stored as text.
- Saving never overwrites a file and never uses a name Windows refuses.
- It sends no data anywhere except the page requests you start. The only thing a site learns is a User-Agent with a link to this project.

## Things to know

- siphon will fetch any address you type, including `localhost` and addresses on your own network. That is fine for a program you run yourself.
- The Windows programs are not code-signed, so Windows SmartScreen may warn on first run. Each release lists a SHA-256 checksum of its zip so you can check your download.
