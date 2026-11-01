/**
 * Small validators used by forms and inline checks. They intentionally avoid
 * pulling in a dependency for network parsing.
 */

export function isIPv4(value: string): boolean {
  const parts = value.split(".");
  if (parts.length !== 4) return false;
  return parts.every((part) => {
    if (!/^\d{1,3}$/.test(part)) return false;
    if (part.length > 1 && part.startsWith("0")) return false;
    const n = Number(part);
    return n >= 0 && n <= 255;
  });
}

function parseIPv6(value: string): bigint | null {
  let input = value.trim().toLowerCase();
  if (!input || !/^[0-9a-f:.]+$/.test(input)) return null;

  let tail: string[] = [];
  const lastColon = input.lastIndexOf(":");
  const possibleV4 = input.slice(lastColon + 1);
  if (possibleV4.includes(".")) {
    if (!isIPv4(possibleV4)) return null;
    const octets = possibleV4.split(".").map(Number);
    tail = [
      ((octets[0] << 8) | octets[1]).toString(16),
      ((octets[2] << 8) | octets[3]).toString(16),
    ];
    input = `${input.slice(0, lastColon + 1)}${tail.join(":")}`;
    // If the address was only the dotted quad, that is not valid IPv6.
    if (input === tail.join(":")) return null;
  }

  const doubleColons = input.split("::").length - 1;
  if (doubleColons > 1) return null;

  let groups: string[];
  if (doubleColons === 1) {
    const [head, rest] = input.split("::");
    const headGroups = head ? head.split(":") : [];
    const restGroups = rest ? rest.split(":") : [];
    const missing = 8 - headGroups.length - restGroups.length;
    if (missing < 1) return null;
    groups = [...headGroups, ...Array<string>(missing).fill("0"), ...restGroups];
  } else {
    groups = input.split(":");
  }

  if (groups.length !== 8) return null;

  let result = 0n;
  for (const group of groups) {
    if (!/^[0-9a-f]{1,4}$/.test(group)) return null;
    result = (result << 16n) | BigInt(Number.parseInt(group, 16));
  }
  return result;
}

export function isIPv6(value: string): boolean {
  return parseIPv6(value) !== null;
}

export function isIPAddress(value: string): boolean {
  return isIPv4(value) || isIPv6(value);
}

/**
 * Accepts an IPv4/IPv6 address or a VyOS interface name (unnumbered peer).
 */
export function isNeighborAddress(value: string): boolean {
  if (isIPAddress(value)) return true;
  return /^[a-zA-Z][a-zA-Z0-9._-]{0,63}$/.test(value);
}

export function isPrefix(value: string): boolean {
  const trimmed = value.trim();
  const slash = trimmed.lastIndexOf("/");
  if (slash <= 0) return false;
  const address = trimmed.slice(0, slash);
  const lengthRaw = trimmed.slice(slash + 1);
  if (!/^\d{1,3}$/.test(lengthRaw)) return false;
  const length = Number(lengthRaw);
  if (lengthRaw.length > 1 && lengthRaw.startsWith("0")) return false;

  if (isIPv4(address)) {
    if (length < 0 || length > 32) return false;
    const mask = length === 0 ? 0 : (0xffffffff << (32 - length)) >>> 0;
    const octets = address.split(".").map(Number);
    const numeric =
      ((octets[0] << 24) >>> 0) +
      (octets[1] << 16) +
      (octets[2] << 8) +
      octets[3];
    return (numeric & ~mask) >>> 0 === 0;
  }

  if (isIPv6(address)) {
    if (length < 0 || length > 128) return false;
    const numeric = parseIPv6(address);
    if (numeric === null) return false;
    const hostBits = 128 - length;
    if (hostBits === 0) return true;
    const mask = (1n << BigInt(hostBits)) - 1n;
    return (numeric & mask) === 0n;
  }

  return false;
}

/**
 * CIDR notation with host bits allowed (interface addressing), e.g.
 * `10.100.0.1/24` or `2001:db8::1/64`. Prefix-list rules use `isPrefix`
 * instead because those require canonical network addresses.
 */
export function isCidr(value: string): boolean {
  const trimmed = value.trim();
  const slash = trimmed.lastIndexOf("/");
  if (slash <= 0 || slash === trimmed.length - 1) return false;
  const address = trimmed.slice(0, slash);
  const lengthRaw = trimmed.slice(slash + 1);
  if (!/^\d{1,3}$/.test(lengthRaw)) return false;
  if (lengthRaw.length > 1 && lengthRaw.startsWith("0")) return false;
  const length = Number(lengthRaw);
  if (isIPv4(address)) return length >= 0 && length <= 32;
  if (isIPv6(address)) return length >= 0 && length <= 128;
  return false;
}

/**
 * WireGuard keys are Base64-encoded 32-byte values: 43 base64 characters plus
 * one `=` padding character.
 */
export function isWireGuardKey(value: string): boolean {
  return /^[A-Za-z0-9+/]{43}=$/.test(value.trim());
}

/**
 * Endpoint host names accepted for WireGuard peers. An IP address is also
 * valid; this only covers DNS names (labels, dots, optional single trailing
 * dot, max 253 characters).
 */
export function isHostname(value: string): boolean {
  const trimmed = value.trim().replace(/\.$/, "");
  if (!trimmed || trimmed.length > 253) return false;
  return trimmed.split(".").every((label) => {
    if (!label || label.length > 63) return false;
    return /^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?$/.test(label);
  });
}

/**
 * WireGuard endpoint: an IPv4/IPv6 address (optionally bracketed), or a fully
 * qualified host name. The API requires a dotted FQDN with an alphabetic TLD,
 * so a bare single-label host is rejected here instead of by the device.
 */
export function isEndpointHost(value: string): boolean {
  const trimmed = value.trim();
  if (!trimmed || /\s/.test(trimmed)) return false;
  const bracketed =
    trimmed.startsWith("[") && trimmed.endsWith("]")
      ? trimmed.slice(1, -1)
      : trimmed;
  if (isIPAddress(bracketed)) return true;
  if (!isHostname(trimmed)) return false;
  const labels = trimmed.replace(/\.$/, "").split(".");
  if (labels.length < 2) return false;
  return /^[A-Za-z]{2,63}$/.test(labels[labels.length - 1]);
}

export function prefixMatchesAf(
  prefix: string,
  af: "ipv4-unicast" | "ipv6-unicast",
): boolean {
  const slash = prefix.lastIndexOf("/");
  if (slash <= 0) return false;
  const address = prefix.slice(0, slash).trim();
  return af === "ipv4-unicast" ? isIPv4(address) : isIPv6(address);
}

/** AS numbers are unsigned 32-bit integers. */
export function isValidAsn(value: number | string | null | undefined): boolean {
  if (value === null || value === undefined || value === "") return false;
  const n = typeof value === "number" ? value : Number(value);
  return Number.isInteger(n) && n >= 1 && n <= 4294967295;
}

export function isValidLocalAs(value: number): boolean {
  return isValidAsn(value) && value !== 23456;
}

export const AF_LABEL: Record<"ipv4-unicast" | "ipv6-unicast", string> = {
  "ipv4-unicast": "IPv4 unicast",
  "ipv6-unicast": "IPv6 unicast",
};
