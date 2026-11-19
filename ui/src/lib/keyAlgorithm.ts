// Best-effort JWS algorithm of a public key the staff types in (onboarding), to
// pre-fill a policy's signing algorithms. Mirrors the backend's inference: RSA ->
// RS256, EC P-256 -> ES256, Ed25519 -> EdDSA. null = unknown (the backend
// decides; it warns if a policy's algorithm matches none of the keys).

// DER-encoded OBJECT IDENTIFIERs (tag + length + value), as hex.
const RSA = "06092a864886f70d010101"; // rsaEncryption
const EC = "06072a8648ce3d0201"; // id-ecPublicKey
const P256 = "06082a8648ce3d030107"; // prime256v1
const ED25519 = "06032b6570"; // id-Ed25519

function fromJwk(jwk: Record<string, unknown>): string | null {
  if (typeof jwk.alg === "string" && jwk.alg) return jwk.alg;
  if (jwk.kty === "RSA") return "RS256";
  if (jwk.kty === "EC" && jwk.crv === "P-256") return "ES256";
  if (jwk.kty === "OKP" && jwk.crv === "Ed25519") return "EdDSA";
  return null;
}

function fromPem(pem: string): string | null {
  const b64 = pem.replace(/-----[^-]+-----/g, "").replace(/\s+/g, "");
  let hex = "";
  try {
    const bin = atob(b64);
    for (let i = 0; i < bin.length; i++) hex += bin.charCodeAt(i).toString(16).padStart(2, "0");
  } catch {
    return null;
  }
  // rsaEncryption / id-ecPublicKey name only a key (signature OIDs differ), so
  // they win; the Ed25519 OID is also a certificate's signature algorithm.
  if (hex.includes(RSA)) return "RS256";
  if (hex.includes(EC)) return hex.includes(P256) ? "ES256" : null;
  if (hex.includes(ED25519)) return "EdDSA";
  return null;
}

export function keyAlgorithm(text: string): string | null {
  const t = text.trim();
  if (!t) return null;
  if (t.startsWith("{")) {
    try {
      return fromJwk(JSON.parse(t));
    } catch {
      return null;
    }
  }
  return t.includes("-----BEGIN") ? fromPem(t) : null;
}
