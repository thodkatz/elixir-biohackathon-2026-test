# Planning a Coder template locally with OpenTofu

Seen 2026-11-10 (slice 2 of the experiments track). The dev VM has no `terraform` or `tofu`, and
`nix shell nixpkgs#opentofu` fails here with `error: creating directory "/nix/store/.links": Read-only file system`.
The release binary works (the coder provider downloads from the registry on `init`):

```bash
mkdir -p "$SCRATCH/tofu" && cd "$SCRATCH/tofu"
curl -sSL -o t.zip https://github.com/opentofu/opentofu/releases/download/v1.10.7/tofu_1.10.7_linux_amd64.zip && unzip -oq t.zip
export SPE_TOFU=$PWD/tofu TF_PLUGIN_CACHE_DIR=$SCRATCH/tfcache
```

The coder provider plans with no Coder server. A parameter's value comes from the environment,
`CODER_PARAMETER_<sha256 hex of the parameter name>=<value>` (a list parameter as a JSON string), and
`CODER_WORKSPACE_TRANSITION=start` makes `start_count` 1. `tofu plan -out p && tofu show -json p` gives
`planned_values.outputs`; `coder_agent.main.token` is unknown at plan time, so anything that includes it (the
template's `ansible_vars`) is unknown too: test a value that leaves it out. `tofu console` does not read the
data sources (`(known after apply)`).
