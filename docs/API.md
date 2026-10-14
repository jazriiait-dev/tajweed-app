# API reference

For whoever builds the mobile and web app. Every path below starts with
`/api/v1`, except `/health`.

## Conventions

- Requests and replies are JSON in UTF-8. Dates are UTC, like `2026-10-11T03:50:00.123456Z`.
- Send the access token as `Authorization: Bearer <token>`.
- Unknown fields in a request are refused.
- Errors always look like this, and the app translates by `code`:

```json
{"error": {"code": "email_taken", "message": "An account with this email already exists."}}
```

Validation errors (`422 invalid_input`) add `details`, a list of
`{"field": "email", "problem": "..."}`.

## Signing in and staying signed in

1. `register` or `login` returns `access_token` (30 minutes), `expires_in`
   in seconds, and `refresh_token` (30 days).
2. When a call answers `401 session_expired`, call `refresh` with the refresh
   token. It returns a new pair. **Store the new refresh token and discard the
   old one.** Presenting an old one again signs the account out everywhere.
3. On `401` with any other code from `refresh`, send the person to sign in.

A child has no login. The parent's session calls
`POST /children/{id}/session`, which returns an access token that acts as the
child for 60 minutes, with no refresh token. Call it again when it expires.

## Routes

"Who" is the role required. "Anyone" needs no token.

| Method and path | Who | What it does |
| --- | --- | --- |
| `GET /health` | Anyone | `{"status":"ok"}` when the API and database work |
| `POST /auth/register` | Anyone | Create a student or parent account and sign in. Returns 201 |
| `POST /auth/login` | Anyone | Sign in |
| `POST /auth/refresh` | Anyone | Exchange a refresh token for a new pair |
| `POST /auth/logout` | Anyone | End the session of a refresh token. Returns 204 |
| `GET /me` | Signed in | My profile and roles |
| `PATCH /me` | Adult | Change my name, language or time zone |
| `POST /me/password` | Adult | Change my password. Signs out other devices and returns a new pair |
| `POST /me/roles` | Adult | Add the `student` or `parent` role to my account |
| `GET /children` | Parent | My child profiles |
| `POST /children` | Parent | Create a child profile. Returns 201 |
| `PATCH /children/{child_id}` | Parent | Change my child's name, language or time zone |
| `POST /children/{child_id}/session` | Parent | Get an access token that acts as my child |
| `GET /riwayat` | Anyone | The riwayat and whether each is available |
| `GET /quran/{riwaya}/surahs` | Anyone | The 114 surahs with names and ayah counts, and the source notice to display |
| `GET /quran/{riwaya}/surahs/{number}` | Anyone | The ayat of a surah. Optional `?from=` and `?to=` |
| `GET /admin/users` | Admin | List accounts. Optional `?role=`, `?search=`, `?limit=`, `?offset=` |
| `POST /admin/users/{user_id}/active` | Admin | Enable or disable an account |
| `POST /admin/users/{user_id}/password` | Admin | Set a new password for someone locked out. Returns 204 |
| `GET /admin/teachers` | Admin | List teachers |
| `POST /admin/teachers` | Admin | Create a teacher account. Returns 201 |
| `PATCH /admin/teachers/{teacher_id}` | Admin | Change a teacher's details or mark them verified |
| `GET /admin/actions` | Admin | The record of admin actions. Optional `?limit=` |
| `POST /admin/riwayat/{code}/approve` | Admin | Record that a reviewer has checked an imported text |

"Adult" means any signed-in account that is not a child profile.

A riwaya that is imported but not yet approved answers `404
riwaya_not_available` to everyone except admins, who can read it to check it.

## Request bodies

| Route | Fields |
| --- | --- |
| `POST /auth/register` | `email`, `password` (8 to 128 characters), `display_name`, `account_type` (`student` or `parent`), `confirms_adult` (must be `true`), optional `language` (`ar`, `en`, `fr`; default `ar`), optional `timezone` (default `UTC`) |
| `POST /auth/login` | `email`, `password` |
| `POST /auth/refresh`, `POST /auth/logout` | `refresh_token` |
| `PATCH /me`, `PATCH /children/{child_id}` | any of `display_name`, `language`, `timezone` |
| `POST /me/password` | `current_password`, `new_password` |
| `POST /me/roles` | `role` (`student` or `parent`) |
| `POST /children` | `display_name`, `guardian_consent` (must be `true`), optional `language`, `timezone` |
| `POST /admin/users/{user_id}/active` | `active` (`true` or `false`) |
| `POST /admin/users/{user_id}/password` | `new_password` |
| `POST /admin/teachers` | `email`, `password`, `display_name`, `gender` (`male` or `female`), `riwayat` (list of codes), `languages` (list), optional `credentials`, `language`, `timezone` |
| `PATCH /admin/teachers/{teacher_id}` | any of `gender`, `credentials`, `riwayat`, `languages`, `verified` |
| `POST /admin/riwayat/{code}/approve` | `reviewer_name` |

## Error codes

| Status | Codes |
| --- | --- |
| 400 | `adult_required`, `weak_password`, `consent_required`, `too_many_children`, `bad_range`, `unknown_role`, `unknown_riwaya`, `cannot_disable_self`, `no_password`, `no_text`, `already_approved` |
| 401 | `not_signed_in`, `invalid_token`, `session_expired`, `wrong_credentials`, `invalid_refresh_token`, `refresh_token_reused`, `session_ended` |
| 403 | `not_allowed`, `managed_by_parent`, `account_disabled`, `wrong_password` |
| 404 | `not_found`, `user_not_found`, `child_not_found`, `teacher_not_found`, `riwaya_not_found`, `riwaya_not_available`, `surah_not_found` |
| 405 | `method_not_allowed` |
| 409 | `email_taken` |
| 413 | `too_large` |
| 422 | `invalid_input` |
| 429 | `account_locked` |
| 500 | `server_error` |
