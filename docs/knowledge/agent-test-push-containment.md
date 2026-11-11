# Containing a test agent's pushes on a controller-built instance

When a coding agent is tested inside a workspace (slice 7 of the experiments track, 2026-11-11), its `git push`
must not reach a real remote. Slice 7 pointed the clone's push URL at a bare repo on the VM (`git -C ~/sperange
remote set-url --push origin ~/push-relay.git`) and relayed branches to the fork by hand:

    git fetch ssh://agent-service-1/home/ubuntu/push-relay.git <b>:refs/remotes/relay/<b>
    git push origin relay/<b>:refs/heads/<b>

**A rebuild undoes it.** Every `create.yml` run sets the push URL again (`roles/repo`, `spe_repo_push_url`, by
default the SSH form of `spe_repo_url`, i.e. upstream `git@github.com:kraatz/…`). After the VM was rebuilt from
`experiment/trs-guard`, the agent's `git push origin experiment/trs-guard` went to **upstream**, not the relay.

**And the push was accepted:** `agent-service-1`'s `~/.ssh/id_ed25519` (made 2026-10-14, not by our roles)
authenticates to GitHub as kraatz (`ssh -T git@github.com` → `Hi kraatz!`). Raised upstream as an issue; the key
and the stray branch are kraatz's to handle (the user's ruling, PR #95).

Before letting an agent push from a workspace, after **every** build:

    ssh <host> 'ssh -T git@github.com 2>&1 | head -1; git -C ~/sperange remote get-url --push origin'

and set the relay push URL again if the build reset it.
