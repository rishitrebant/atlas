const fs = require("fs");
const path = require("path");
const solc = require("solc");

const contractPath = path.join(__dirname, "..", "contracts", "AtlasRegistry.sol");
const source = fs.readFileSync(contractPath, "utf8");

const input = {
  language: "Solidity",
  sources: {
    "AtlasRegistry.sol": { content: source },
  },
  settings: {
    optimizer: { enabled: true, runs: 200 },
    outputSelection: {
      "*": { "*": ["abi", "evm.bytecode.object"] },
    },
  },
};

const output = JSON.parse(solc.compile(JSON.stringify(input)));

if (output.errors) {
  const fatal = output.errors.filter((e) => e.severity === "error");
  output.errors.forEach((e) => console.error(e.formattedMessage));
  if (fatal.length > 0) {
    process.exit(1);
  }
}

const contract = output.contracts["AtlasRegistry.sol"]["AtlasRegistry"];

fs.mkdirSync(path.join(__dirname, "..", "artifacts"), { recursive: true });
fs.writeFileSync(
  path.join(__dirname, "..", "artifacts", "AtlasRegistry.json"),
  JSON.stringify(
    {
      abi: contract.abi,
      bytecode: "0x" + contract.evm.bytecode.object,
    },
    null,
    2
  )
);

console.log("Compiled OK. ABI entries:", contract.abi.length);
