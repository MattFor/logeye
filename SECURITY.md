# Security policy

## Supported versions

Security fixes go into the latest release only.

## Reporting a vulnerability

Please do not open a public issue. Report it privately through
[GitHub security advisories](https://github.com/MattFor/logeye/security/advisories/new)
or by email to mattfor@relaxy.xyz. You should get an answer within a week.

## Keep in mind

LogEye prints the values of your variables. Anything it logs, a password or an
API key included, ends up wherever its output goes: the terminal, CI logs, or a
log file. Keep it out of production code paths that handle secrets.
