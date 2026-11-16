// Deploys AtlasRegistry to the local Hardhat node and prints the address
// you must paste into Backend/.env as CONTRACT_ADDRESS.
const { ethers } = require("ethers");
const fs = require("fs");
const path = require("path");

const RPC = process.env.RPC_URL || "http://127.0.0.1:8545";
// Hardhat's well-known TEST account #0 -- public, worthless, local only.
const KEY = process.env.DEPLOYER_KEY ||
  "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80";

async function main() {
  const artifact = JSON.parse(
    fs.readFileSync(path.join(__dirname, "..", "artifacts", "AtlasRegistry.json"), "utf8")
  );
  const provider = new ethers.JsonRpcProvider(RPC);
  const wallet = new ethers.Wallet(KEY, provider);
  const nonce = await provider.getTransactionCount(wallet.address, "latest");
  const factory = new ethers.ContractFactory(artifact.abi, artifact.bytecode, wallet);
  const contract = await factory.deploy({ nonce });
  await contract.waitForDeployment();
  const address = await contract.getAddress();
  console.log("\nAtlasRegistry deployed.");
  console.log("Deployer:", wallet.address);
  console.log("\n>>> Put this in Backend/.env <<<");
  console.log("CONTRACT_ADDRESS=" + address + "\n");
}
main().catch((e) => { console.error("Deploy failed. Is `npm run node` running?\n", e.message); process.exit(1); });
