import type { Role } from "@/lib/types";
import { ROLE_RANK } from "@/lib/types";

export function roleAtLeast(role: Role | undefined | null, minimum: Role): boolean {
  if (!role) return false;
  return ROLE_RANK[role] >= ROLE_RANK[minimum];
}

export function isAdmin(role: Role | undefined | null): boolean {
  return role === "admin";
}

/** Operator and admin may mutate BGP objects; viewers are read-only. */
export function canWrite(role: Role | undefined | null): boolean {
  return roleAtLeast(role, "operator");
}

export const ROLE_LABEL: Record<Role, string> = {
  admin: "Administrator",
  operator: "Operator",
  viewer: "Viewer",
};

export const ROLE_DESCRIPTION: Record<Role, string> = {
  admin: "Full access, including routers, users and audit",
  operator: "Can change BGP configuration",
  viewer: "Read-only access to routers and BGP status",
};
