"use client";

import { useRef, useState } from "react";
import { FileSpreadsheet, Loader2, Upload } from "lucide-react";
import type { UploadedFile } from "@/lib/api";
import { uploadFiles } from "@/lib/api";
import { cn } from "@/lib/utils";

type Props = {
  sessionId: string | null;
  files: UploadedFile[];
  onUploaded: (files: UploadedFile[]) => void;
};

export function UploadPanel({ sessionId, files, onUploaded }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleFiles(list: FileList | null) {
    if (!list?.length || !sessionId) return;
    setBusy(true);
    setError(null);
    try {
      const uploaded = await uploadFiles(sessionId, list);
      onUploaded(uploaded);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  return (
    <section className="space-y-4">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          void handleFiles(e.dataTransfer.files);
        }}
        className={cn(
          "relative flex flex-col items-center justify-center gap-3 border border-dashed px-6 py-10 transition",
          "border-[var(--line)] bg-[var(--panel)]/60",
          dragging && "border-[var(--accent)] bg-[var(--accent-soft)]",
          !sessionId && "opacity-50 pointer-events-none",
        )}
      >
        <Upload className="h-7 w-7 text-[var(--accent)]" strokeWidth={1.5} />
        <div className="text-center">
          <p className="font-display text-lg text-[var(--ink)]">
            Drop CSV or Excel files
          </p>
          <p className="mt-1 text-sm text-[var(--muted)]">
            Add one or more spreadsheets to this session
          </p>
        </div>
        <button
          type="button"
          disabled={!sessionId || busy}
          onClick={() => inputRef.current?.click()}
          className="mt-1 inline-flex items-center gap-2 bg-[var(--ink)] px-4 py-2 text-sm text-[var(--paper)] transition hover:bg-[var(--accent)]"
        >
          {busy ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" /> Uploading…
            </>
          ) : (
            "Browse files"
          )}
        </button>
        <input
          ref={inputRef}
          type="file"
          accept=".csv,.xlsx,.xls"
          multiple
          className="hidden"
          onChange={(e) => void handleFiles(e.target.files)}
        />
      </div>

      {error && (
        <p className="text-sm text-red-700 bg-red-50 px-3 py-2">{error}</p>
      )}

      {files.length > 0 && (
        <ul className="space-y-2">
          {files.map((f) => (
            <li
              key={f.id}
              className="flex items-start gap-3 border-b border-[var(--line)] pb-3"
            >
              <FileSpreadsheet className="mt-0.5 h-4 w-4 shrink-0 text-[var(--accent)]" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-[var(--ink)]">
                  {f.filename}
                </p>
                <p className="text-xs text-[var(--muted)]">
                  table <code className="text-[var(--accent)]">{f.duckdb_table_name}</code>
                  {" · "}
                  {f.schema.row_count} rows · {f.schema.column_count} cols
                </p>
                <p className="mt-1 truncate text-xs text-[var(--muted)]">
                  {f.schema.columns.map((c) => c.name).join(", ")}
                </p>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
