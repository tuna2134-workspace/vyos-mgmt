import type { FieldValues, Path, UseFormSetError } from "react-hook-form";

import { ApiError } from "@/lib/api";
import type { ValidationDetail } from "@/lib/types";

function asValidationDetails(
  details: ApiError["details"],
): ValidationDetail[] {
  if (!Array.isArray(details)) return [];
  return details.filter(
    (item): item is ValidationDetail =>
      !!item &&
      typeof item === "object" &&
      Array.isArray((item as ValidationDetail).loc),
  );
}

/**
 * Map a FastAPI 422 `details: [{loc, msg, ...}]` payload onto react-hook-form
 * fields. Returns true when at least one field error was applied; otherwise the
 * caller should surface `error.message` at the top of the form.
 */
export function applyServerFormErrors<T extends FieldValues>(
  error: unknown,
  setError: UseFormSetError<T>,
  knownFields?: readonly string[],
): boolean {
  if (!(error instanceof ApiError)) return false;
  const details = asValidationDetails(error.details);
  let applied = false;
  let allMapped = true;

  for (const detail of details) {
    // Only map flat body fields (e.g. ["body", "host"]). Nested FastAPI paths
    // such as ["body", "address_families", "ipv4-unicast", ...] do not map to
    // a registered form field; leave them to the form-level error banner.
    const path = detail.loc.filter(
      (part): part is string =>
        typeof part === "string" &&
        part !== "body" &&
        part !== "query" &&
        part !== "path",
    );

    if (
      path.length !== 1 ||
      (knownFields && !knownFields.includes(path[0]))
    ) {
      allMapped = false;
      continue;
    }

    setError(path[0] as Path<T>, {
      type: "server",
      message: detail.msg || "Invalid value",
    });
    applied = true;
  }

  // Return true only when every detail was attached to a field. If some were
  // nested/unmapped, callers also show the API message so nothing is silent.
  return applied && allMapped;
}

export function validationMessages(error: unknown): string[] {
  if (!(error instanceof ApiError)) return [];
  return asValidationDetails(error.details).map((d) => d.msg);
}
