# Security Policy

## Reporting a vulnerability

Report vulnerabilities privately through GitHub's private vulnerability
reporting: open this repository's **Security** tab and choose **Report a
vulnerability**, or go straight to
<https://github.com/weirdapps/yahoo-access/security/advisories/new>.
Please do not open a public issue for a vulnerability.

## Credentials

App passwords are stored in the macOS Keychain, never in the repo. The config
file `~/.yahoo-mail/accounts.json` contains no passwords and is gitignored.
Keychain items created by `setup.sh` can be read back without a prompt by
`/usr/bin/security`, which is how the server reads them, so they are protected
from other users of the Mac but not from programs running under your own account.
