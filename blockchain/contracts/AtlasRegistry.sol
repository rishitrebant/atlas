// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title ATLAS Registry
/// @notice On-chain proof log for ATLAS. Only hashes are ever written here —
/// never raw student data, names, emails, or card UIDs. The private database
/// (FastAPI + Postgres) remains the source of truth for everything else;
/// this contract only answers "was this exact proof logged, and is it still
/// valid?" for anyone who wants to verify it, with no login required.
contract AtlasRegistry {
    /// @dev Mirrors app/models.py's event taxonomy on the backend.
    enum EventType {
        CredentialIssued,
        CredentialRevoked,
        GateEntry,
        GateExit
    }

    struct ProofRecord {
        bool exists;
        EventType eventType;
        uint256 timestamp;
        bool revoked;
    }

    address public immutable owner;

    mapping(bytes32 => ProofRecord) private records;

    event ProofLogged(
        bytes32 indexed proofHash,
        EventType indexed eventType,
        uint256 timestamp
    );

    event ProofRevoked(bytes32 indexed proofHash, uint256 timestamp);

    error NotOwner();
    error ProofAlreadyExists();
    error ProofDoesNotExist();

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    constructor() {
        owner = msg.sender;
    }

    /// @notice Writes a new proof to the chain. Only the backend's
    /// configured wallet (the contract deployer) may call this.
    /// @param proofHash SHA-256 digest computed off-chain by the backend
    /// over the canonical, non-sensitive fields of a credential or a gate
    /// entry/exit event. Never raw personal data.
    function logProof(bytes32 proofHash, EventType eventType) external onlyOwner {
        if (records[proofHash].exists) revert ProofAlreadyExists();

        records[proofHash] = ProofRecord({
            exists: true,
            eventType: eventType,
            timestamp: block.timestamp,
            revoked: false
        });

        emit ProofLogged(proofHash, eventType, block.timestamp);
    }

    /// @notice Marks a previously logged proof as revoked (e.g. a
    /// credential that's been invalidated after issuance). Does not delete
    /// the record — matches the backend's own revoke semantics, which keep
    /// history rather than erasing it.
    function revokeProof(bytes32 proofHash) external onlyOwner {
        if (!records[proofHash].exists) revert ProofDoesNotExist();

        records[proofHash].revoked = true;

        emit ProofRevoked(proofHash, block.timestamp);
    }

    /// @notice Public, unauthenticated read — anyone can verify a proof
    /// without an account or an API key, matching the "verifier later
    /// checks the record" flow from the project brief.
    function verifyProof(bytes32 proofHash)
        external
        view
        returns (bool exists, EventType eventType, uint256 timestamp, bool revoked)
    {
        ProofRecord memory record = records[proofHash];
        return (record.exists, record.eventType, record.timestamp, record.revoked);
    }
}
