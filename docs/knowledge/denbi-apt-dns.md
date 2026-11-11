# de.NBI: `create.yml` fails at `base : Install packages` (apt cache)

**Symptom** (2026-11-11, denbi-agui-01 on agent-service-1): `create.yml` stops at `base : Install packages` with
`Failed to update apt cache after 5 retries:` (empty reason). On the VM, `sudo apt-get update` hangs with no output.
Two sessions running it at once add `E: Could not get lock /var/lib/apt/lists/lock. It is held by process … (apt-get)`.

**Cause:** the VM cannot resolve the Ubuntu archives. `curl -m 10 http://archive.ubuntu.com/ubuntu/` gives
`curl: (28) Resolving timed out after 10000 milliseconds`, and so does `de.archive…`. `download.docker.com` and
`github.com` answer 200. The apt sources are `nova.clouds.archive.ubuntu.com` and `security.ubuntu.com`.

**What to do:**
- Check resolution first:
  `ssh agent-service-1 'curl -sS -o /dev/null -m 10 -w "%{http_code}\n" http://archive.ubuntu.com/ubuntu/'`.
  Retry the build only once that gives 200.
- Never leave an `apt-get update` probe hanging over ssh: it holds the apt lock, and the next build fails on the lock
  instead. Run probes with `timeout`, and kill a leftover one with `sudo kill <pid>` (`pgrep -a apt-get`).
- The failing run changes nothing on the VM (`changed=0` in its recap): `base` runs before any role that rewrites
  the stack.
