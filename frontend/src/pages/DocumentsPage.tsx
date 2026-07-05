import { type DragEvent, type ChangeEvent, useCallback, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { documentsApi, type DocumentResponse, type DocumentStatus } from '../api/documents';

// ── Status badge ──────────────────────────────────────────────────────────────

const STATUS_STYLES: Record<DocumentStatus, string> = {
  queued: 'bg-yellow-900/40 text-yellow-300 border-yellow-700',
  processing: 'bg-blue-900/40 text-blue-300 border-blue-700',
  ready: 'bg-green-900/40 text-green-300 border-green-700',
  failed: 'bg-red-900/40 text-red-300 border-red-700',
};

function StatusBadge({ status }: { status: DocumentStatus }) {
  return (
    <span className={`text-xs font-medium px-2 py-0.5 rounded border ${STATUS_STYLES[status]}`}>
      {status}
    </span>
  );
}

const TERMINAL: DocumentStatus[] = ['ready', 'failed'];

// ── File size formatter ───────────────────────────────────────────────────────

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

// ── Document row ──────────────────────────────────────────────────────────────

function DocumentRow({ doc, onDelete }: { doc: DocumentResponse; onDelete: (id: string) => void }) {
  const [confirming, setConfirming] = useState(false);

  // Auto-refresh non-terminal docs via TanStack Query polling
  useQuery({
    queryKey: ['doc-status', doc.id],
    queryFn: () => documentsApi.getStatus(doc.id),
    refetchInterval: TERMINAL.includes(doc.status) ? false : 3000,
    enabled: !TERMINAL.includes(doc.status),
  });

  return (
    <div className="flex items-start justify-between gap-4 py-3 border-b border-gray-800 last:border-0">
      <div className="min-w-0">
        <p className="text-sm font-medium text-gray-100 truncate">{doc.title}</p>
        <p className="text-xs text-gray-500 mt-0.5 truncate">
          {doc.filename} · {fmtBytes(doc.file_size)}
          {doc.status === 'ready' && ` · ${doc.chunk_count} chunks`}
        </p>
        {doc.error_message && (
          <p className="text-xs text-red-400 mt-1 truncate">{doc.error_message}</p>
        )}
      </div>
      <div className="flex items-center gap-3 shrink-0">
        <StatusBadge status={doc.status} />
        {confirming ? (
          <div className="flex gap-2">
            <button
              onClick={() => onDelete(doc.id)}
              className="text-xs text-red-400 hover:text-red-300"
            >
              Confirm
            </button>
            <button
              onClick={() => setConfirming(false)}
              className="text-xs text-gray-500 hover:text-gray-300"
            >
              Cancel
            </button>
          </div>
        ) : (
          <button
            onClick={() => setConfirming(true)}
            className="text-xs text-gray-600 hover:text-red-400 transition-colors"
            aria-label="Delete document"
          >
            ✕
          </button>
        )}
      </div>
    </div>
  );
}

// ── Upload zone ───────────────────────────────────────────────────────────────

const ACCEPTED = '.pdf,.docx,.txt,.md,.html';

function UploadZone({ onFile }: { onFile: (f: File) => void }) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDrop = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setDragging(false);
      const file = e.dataTransfer.files[0];
      if (file) onFile(file);
    },
    [onFile]
  );

  const handleChange = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) onFile(file);
    e.target.value = '';
  };

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => inputRef.current?.click()}
      onKeyDown={(e) => e.key === 'Enter' && inputRef.current?.click()}
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      className={`flex flex-col items-center justify-center rounded-xl border-2 border-dashed
        p-8 cursor-pointer transition-colors select-none
        ${dragging ? 'border-indigo-500 bg-indigo-950/30' : 'border-gray-700 hover:border-indigo-600 bg-gray-900'}`}
    >
      <svg
        className="w-8 h-8 text-gray-500 mb-3"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={1.5}
          d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"
        />
      </svg>
      <p className="text-sm text-gray-400">
        <span className="text-indigo-400">Click to upload</span> or drag & drop
      </p>
      <p className="text-xs text-gray-600 mt-1">PDF, DOCX, TXT, MD, HTML</p>
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPTED}
        className="hidden"
        onChange={handleChange}
      />
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export function DocumentsPage() {
  const qc = useQueryClient();
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ['documents'],
    queryFn: () => documentsApi.list(),
    // Refetch while any doc is non-terminal
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? [];
      return items.some((d) => !TERMINAL.includes(d.status)) ? 3000 : false;
    },
  });

  const uploadMutation = useMutation({
    mutationFn: (file: File) => documentsApi.upload(file, undefined, setUploadProgress),
    onSuccess: () => {
      setUploadProgress(null);
      setUploadError(null);
      qc.invalidateQueries({ queryKey: ['documents'] });
    },
    onError: (err: unknown) => {
      setUploadProgress(null);
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Upload failed.';
      setUploadError(msg);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => documentsApi.delete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['documents'] }),
  });

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100 p-6">
      <div className="max-w-2xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-indigo-600 flex items-center justify-center shrink-0">
              <span className="text-white font-bold text-base">V</span>
            </div>
            <div>
              <h1 className="font-semibold text-lg leading-none">Documents</h1>
              <p className="text-xs text-gray-500 mt-0.5">Upload and manage your files</p>
            </div>
          </div>
          <Link
            to="/dashboard"
            className="text-xs text-gray-400 hover:text-gray-200 border border-gray-700 hover:border-gray-500 px-3 py-1.5 rounded-lg transition-colors"
          >
            ← Dashboard
          </Link>
        </div>

        {/* Upload zone */}
        <div className="mb-6">
          <UploadZone onFile={(f) => uploadMutation.mutate(f)} />
          {uploadProgress !== null && (
            <div className="mt-3">
              <div className="flex justify-between text-xs text-gray-400 mb-1">
                <span>Uploading…</span>
                <span>{uploadProgress}%</span>
              </div>
              <div className="w-full bg-gray-800 rounded-full h-1.5">
                <div
                  className="bg-indigo-500 h-1.5 rounded-full transition-all"
                  style={{ width: `${uploadProgress}%` }}
                />
              </div>
            </div>
          )}
          {uploadError && (
            <p className="mt-2 text-xs text-red-400 bg-red-950/40 border border-red-900 rounded-lg px-3 py-2">
              {uploadError}
            </p>
          )}
        </div>

        {/* Document list */}
        <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6">
          <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest mb-4">
            Your documents
            {data && (
              <span className="ml-2 text-gray-600 normal-case font-normal">({data.total})</span>
            )}
          </h2>

          {isLoading && <p className="text-sm text-gray-400">Loading…</p>}

          {data && data.items.length === 0 && (
            <p className="text-sm text-gray-600 py-4 text-center">
              No documents yet — upload your first file above.
            </p>
          )}

          {data?.items.map((doc) => (
            <DocumentRow key={doc.id} doc={doc} onDelete={(id) => deleteMutation.mutate(id)} />
          ))}
        </div>
      </div>
    </div>
  );
}
