"""Provision a MyoLens account and set its role claim (A2, A4).

**Why this script has to exist.** There is no self-registration -- deliberately, it is on the
`Won't` list in SRS §4.2 A as an abuse surface -- and roles are Firebase custom claims, which
only a privileged caller can set. Without a bootstrap path the very first admin is
uncreatable, so nobody can grant anybody anything and `PATCH /v1/admin/clinicians/{uid}` can
never be reached. That is a genuine chicken-and-egg, not an oversight in the API: the first
credential in any system with no public sign-up has to come from outside it.

**Credentials.** Uses Application Default Credentials. Authenticate first with

    gcloud auth application-default login

or run somewhere the environment already supplies them. This script never reads, accepts or
prints a service-account key file: there is a deployment key on this project and the rule about
it is that it goes from disk into a GitHub secret and nowhere else.

**Usage**

    python scripts/bootstrap_accounts.py --project myolens --email you@example.com --role admin
    python scripts/bootstrap_accounts.py --project myolens --email demo@example.com --role clinician

The password is read from the ``MYOLENS_BOOTSTRAP_PASSWORD`` environment variable, or prompted
for without echo. It is never taken as a command-line argument, because arguments land in shell
history and in the process table where any other user on the machine can read them.

Idempotent: running it again for an existing address updates that account's role rather than
failing, so it is safe to re-run when you cannot remember whether you already did.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys

VALID_ROLES = ("clinician", "admin")


def _password() -> str:
    from_env = os.environ.get("MYOLENS_BOOTSTRAP_PASSWORD")
    if from_env:
        return from_env
    first = getpass.getpass("Password for the account: ")
    if len(first) < 12:
        raise SystemExit(
            "Refusing a password under 12 characters. This account can read participant "
            "records; Firebase's own minimum of 6 is not a sensible floor for that."
        )
    if first != getpass.getpass("Confirm: "):
        raise SystemExit("The two passwords did not match. Nothing was changed.")
    return first


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, help="Firebase/GCP project id, e.g. myolens")
    parser.add_argument("--email", required=True)
    parser.add_argument("--role", choices=VALID_ROLES, default="clinician")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without touching the project.",
    )
    args = parser.parse_args()

    if args.dry_run:
        print(f"DRY RUN  would ensure {args.email} exists in {args.project} with role={args.role}")
        return 0

    import firebase_admin
    from firebase_admin import auth

    firebase_admin.initialize_app(options={"projectId": args.project})

    password = _password()

    try:
        user = auth.get_user_by_email(args.email)
        auth.update_user(user.uid, password=password)
        action = "updated"
    except auth.UserNotFoundError:
        user = auth.create_user(email=args.email, password=password, email_verified=True)
        action = "created"

    # The claim the API reads (app/auth.py). Merged rather than replaced, so any future claim on
    # the account survives a role change.
    claims = dict(user.custom_claims or {})
    claims["role"] = args.role
    auth.set_custom_user_claims(user.uid, claims)

    print(f"OK  {action} {args.email}")
    print(f"    uid   {user.uid}")
    print(f"    role  {args.role}")
    print()
    print(
        "The claim reaches the API on the account's next ID token. An already-signed-in browser "
        "keeps its old role until the token refreshes (about an hour) or the user signs out and "
        "in again -- worth knowing before concluding the change did not work."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
