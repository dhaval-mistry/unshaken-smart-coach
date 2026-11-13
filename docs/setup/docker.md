# Install Docker

Docker currently runs PostgreSQL and the optional observability profile in a
consistent environment. The owner-approved design for running FastAPI in Docker
is documented in the
[local backend container design](../architecture/backend-container.md). No
backend Dockerfile or Compose service exists yet.

## Windows

1. Confirm that hardware virtualization is enabled.
2. Install or update WSL 2:

   ```powershell
   wsl --install
   wsl --update
   ```

3. Download and install [Docker Desktop for Windows][docker-windows]. The WSL 2
   backend is appropriate for most Windows contributors.
4. Start Docker Desktop and wait until the Docker engine is running.

## macOS and Linux

Use the installation instructions for your operating system on the
[Docker documentation site][docker-install]. Docker Desktop includes Docker
Compose. Linux contributors may instead install Docker Engine and the Compose
plugin from Docker's repository.

## Verify the installation

Open a new terminal and run:

```text
docker --version
docker compose version
docker run --rm hello-world
```

All three commands should complete successfully. If `docker` exists but
`docker compose` is unavailable, install or update Docker Desktop (recommended
for Windows and macOS) or install the Compose plugin on Linux.

Docker Desktop may have licensing requirements for some larger organizations;
review the terms before using it for commercial work.

[docker-windows]: https://docs.docker.com/desktop/setup/install/windows-install/
[docker-install]: https://docs.docker.com/engine/install/
