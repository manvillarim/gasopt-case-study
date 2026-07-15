# Case-study subjects (Phase 1)

Identity confirmed from primary sources (git `remote.origin.url` + repo README + `package.json`).
Adoption statements are sourced to the repo's own primary claims; precise on-chain TVL figures
are marked "verify via DefiLlama" and must NOT be written into the paper as numbers unless sourced.

## SCOPE (user directive, 2026-07-15)
The study — and the article — cover only the **7 subjects that ship a runnable Foundry test
suite**, which is a hard requirement for the empirical gas methodology of Section 5 (RQ3/RQ5).
The 3 subjects **without** a runnable Foundry gas suite were **dropped**; the user will select 3
replacements later to restore the ten-protocol target. See "Dropped subjects" below.

### In-study subjects (7)
| Dir | Protocol | Category | Identity evidence (primary) | Production contract dir | Foundry gas |
|---|---|---|---|---|---|
| aave-v3-origin | Aave V3 (v3.6/3.7 Origin) | Lending | remote `github.com/aave-dao/aave-v3-origin`; README "Aave V3.x Origin ... complete codebase"; pkg `@aave-dao/aave-v3-origin` | `src/` | ✓ self-contained, 0 fork sites |
| core | Lido | Liquid staking | remote `github.com/lidofinance/core`; pkg `lido-on-ethereum`, desc "Lido on Ethereum ... liquid-staking protocol" | `contracts/` | ✓ (multi-version) |
| core-v3 | Gearbox V3 | Leverage/credit | remote `github.com/Gearbox-protocol/core-v3`; README "Gearbox Protocol ... onchain credit" | `contracts/` | ✓ 0 fork refs |
| morpho-blue | Morpho Blue | Lending | remote `github.com/morpho-org/morpho-blue`; README "Morpho Blue is a non-custodial lending protocol" | `src/` | ✓ |
| openzeppelin-contracts | OpenZeppelin Contracts | Library | remote `github.com/OpenZeppelin/openzeppelin-contracts`; pkg `openzeppelin-solidity`, desc "Secure Smart Contract library for Solidity" | `contracts/` | ✓ |
| seaport | Seaport (OpenSea) | NFT marketplace | remote `github.com/ProjectOpenSea/seaport`; pkg desc "Seaport is a marketplace protocol for ... buying and selling NFTs" | `contracts/` | ✓ (rq5 at runs=200) |
| v4-core | Uniswap V4 Core | DEX | remote `github.com/Uniswap/v4-core`; pkg `@uniswap/v4-core`, desc "Core smart contracts of Uniswap v4" | `src/` | ✓ (rq5 at runs=200) |

### Dropped subjects (3 — no runnable Foundry gas suite; pending replacement)
| Dir | Protocol | Reason dropped |
|---|---|---|
| account-abstraction | ERC-4337 EntryPoint (eth-infinitism) | **Hardhat project, no `foundry.toml`, 0 `.t.sol`** — no Foundry suite at all |
| comet | Compound III (Comet) | 9/10 `.t.sol` are mainnet-deployment/**fork** tests; forge-std deps not installed → not runnable without RPC |
| fluid-contracts-public | Fluid (Instadapp) | 47 `.t.sol` are **fork** tests (require mainnet RPC); `optimizer_runs=10M` OOM risk |

## Adoption evidence (sourced; refine in write-up)
- **Aave V3** — one of the largest DeFi lending protocols by TVL (verify current figure via DefiLlama `/protocol/aave-v3`).
- **account-abstraction** — canonical ERC-4337 EntryPoint; README states it is "deployed by our team on most EVM-compatible networks" (adoption = ubiquity of the singleton, not TVL).
- **Compound III** — major lending protocol (verify TVL via DefiLlama `/protocol/compound-v3`).
- **Lido** — largest liquid-staking protocol on Ethereum (verify staked-ETH TVL via DefiLlama `/protocol/lido`).
- **Gearbox V3** — onchain leverage/credit protocol (verify TVL via DefiLlama `/protocol/gearbox`).
- **Fluid (Instadapp)** — lending/DEX hybrid (verify TVL via DefiLlama `/protocol/fluid`).
- **Morpho Blue** — lending primitive with substantial TVL (verify via DefiLlama `/protocol/morpho-blue`).
- **OpenZeppelin Contracts** — de-facto standard Solidity library; adoption = npm `@openzeppelin/contracts` download volume + dependent-project count (README NPM/GitHub badges), not TVL.
- **Seaport** — primary OpenSea marketplace settlement protocol (adoption = NFT trading volume settled).
- **Uniswap V4 Core** — core pool logic of Uniswap V4 (adoption = Uniswap's position as the largest DEX; verify via DefiLlama `/protocol/uniswap-v4`).

Rule for the paper: for DeFi subjects with a meaningful TVL, cite DefiLlama; for OpenZeppelin,
account-abstraction, Seaport, use the non-TVL adoption signal above (dependents / deployments /
volume), consistent with the article's phrasing "selected by adoption (e.g., TVL, for the DeFi
protocols among them)".
