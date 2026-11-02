# Get ExerciseDB API access

Each backend contributor must use their own ExerciseDB API key. ExerciseDB is
available through RapidAPI and requires RapidAPI authentication headers for
requests.

> **Keep your key private.** Do not share it in Discord, place it in source
> code, include it in screenshots, or add it to `.env.example`. Store it only
> in your local `.env` file or an approved secret manager.

## 1. Create a RapidAPI account

1. Go to [RapidAPI][rapidapi] and create an account or sign in.
2. Verify your account if RapidAPI asks you to do so.
3. Use a personal account unless the team later creates a managed team account.

RapidAPI normally creates a default application when you sign up. An
application owns the API key and provides usage analytics. You may create a
separate application named `unshaken-smart-coach` in the Developer Dashboard
if you want this project's usage separated from your other work.

## 2. Subscribe to ExerciseDB

1. Open the [ExerciseDB API listing][exercisedb].
2. Open the **Pricing** section.
3. Select the **Basic** plan only after confirming that it displays `$0/month`.
4. Read the current request, bandwidth, billing, and overage terms before
   subscribing. Plans and limits can change after this guide is written.
5. Do not select a paid plan for this learning project unless you personally
   intend to pay for it and have discussed the need with the team.

Each contributor is responsible for monitoring their own RapidAPI usage. Avoid
unnecessary calls during development; automated tests should mock ExerciseDB
rather than consume the live quota.

## 3. Test access and locate your key

1. Return to the ExerciseDB **Endpoints** page.
2. Select a small read-only endpoint, such as the body-part list.
3. Select your `unshaken-smart-coach` RapidAPI application, if you created one.
4. Use **Test Endpoint** and confirm that the request succeeds.
5. Find the application's key in the generated code sample or under the
   application's **Authorization** page in the RapidAPI Developer Dashboard.

ExerciseDB requests use these headers:

```text
X-RapidAPI-Key: your personal RapidAPI application key
X-RapidAPI-Host: exercisedb.p.rapidapi.com
```

Do not paste the real key into this document, an issue, a pull request, or a
chat message.

## 4. Create your local `.env` file

From the repository root, copy the safe template only if `.env` does not
already exist. Keep your existing settings if the file is already present.

Windows PowerShell:

```powershell
if (-not (Test-Path -LiteralPath .env)) {
    Copy-Item -LiteralPath .env.example -Destination .env
}
```

macOS or Linux:

```bash
if [ ! -e .env ]; then
    cp .env.example .env
fi
```

Open your `.env` file and replace only the ExerciseDB key placeholder with
your personal key:

```dotenv
EXERCISE_DB_BASE_URL=https://exercisedb.p.rapidapi.com
EXERCISE_DB_HOST=exercisedb.p.rapidapi.com
EXERCISE_DB_API_KEY=replace-with-your-personal-key
EXERCISE_DB_MEDIA_ENABLED=true
```

Keep the base URL and host unchanged unless the project officially changes
providers. Complete the other placeholders in `.env` using their relevant
setup guides.

## 5. Confirm that Git ignores `.env`

Run these commands from the repository root:

```text
git check-ignore .env
git status --short
```

The first command should print `.env`, and `.env` must not appear in the Git
status output. The repository's `.gitignore` already ignores files named
`.env`.

The tracked `.env.example` file must contain variable names and safe
placeholders only. Never replace its `EXERCISE_DB_API_KEY` placeholder with a
real key.

## If a key is exposed

Treat a key as compromised if it appears in Git, Discord, an issue, a pull
request, logs, or a screenshot:

1. Rotate or replace the key immediately in the RapidAPI Developer Dashboard.
2. Update your local `.env` with the replacement key.
3. Tell the project maintainer what was exposed without sending the key itself.
4. Remove the secret from the affected location. Deleting a Git line alone is
   not sufficient because the value can remain in repository history.

See RapidAPI's [API key management documentation][rapidapi-keys] for key
location and rotation instructions.

[rapidapi]: https://rapidapi.com/
[exercisedb]: https://rapidapi.com/justin-WFnsXH_t6/api/exercisedb
[rapidapi-keys]: https://docs.rapidapi.com/v2/docs/keys-and-key-rotation
