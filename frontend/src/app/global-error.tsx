"use client";

import * as React from "react";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  React.useEffect(() => {
    console.error("Global application error", error);
  }, [error]);

  return (
    <html lang="en" className="dark">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#0c1118",
          color: "#e2e8f0",
          fontFamily: "ui-sans-serif, system-ui, sans-serif",
        }}
      >
        <div style={{ maxWidth: 420, padding: 32, textAlign: "center" }}>
          <h1 style={{ fontSize: 20, marginBottom: 8 }}>
            VyOS Control failed to load
          </h1>
          <p style={{ fontSize: 14, color: "#94a3b8", lineHeight: 1.6 }}>
            A fatal client error occurred. Reload the console to recover.
          </p>
          <button
            onClick={reset}
            style={{
              marginTop: 20,
              padding: "9px 16px",
              borderRadius: 8,
              border: "1px solid #334155",
              background: "#111a24",
              color: "#e2e8f0",
              cursor: "pointer",
            }}
          >
            Reload console
          </button>
        </div>
      </body>
    </html>
  );
}
