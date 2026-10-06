# ws-resolve

Resolves a monorepo workspace (`{"packages":[{name,version,deps}]}`) into a deterministic install
order (dependencies first, ties alphabetical), fetches each package's manifest from the internal
registry, and prints levels + integrity hashes. Output is consumed by the deploy tooling, so it must
stay byte-identical.

    node src/cli.ts fixtures/big.json     # Node >= 22.18 runs TypeScript directly (type stripping)
    npm test

Big workspaces in production have 3-5k packages. It runs on Node in CI and on Bun on dev machines.
The internal registry allows at most 16 concurrent requests per client (see `src/registry.ts`).
