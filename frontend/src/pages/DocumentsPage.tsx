/**
 * DocumentsPage — upload and manage ingested documents.
 *
 * Features: drag-and-drop upload, live progress bar, status polling,
 * sort/filter controls, empty state, and a modal delete confirmation.
 */
import { type ChangeEvent, type DragEvent, useCallback, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import toast from 'react-hot-toast';
import { documentsApi, type DocumentResponse, type DocumentStatus } from '../api/documents';
import { Modal } from '../components/ui/Modal';

const TERMINAL: DocumentStatus[] = ['ready', 'failed'];
const ACCEPTED = '.pdf,.docx,.txt,.md,.html';

const STATUS_STYLES: Record<DocumentStatus, string> = {
  queued: 'bg-yellow-900/40 text-yellow-300 border-yellow-700',
  processing: 'bg-blue-900/40 text-blue-300 border-blue-700',
  ready: 'bg-green-900/40 text-green-300 border-green-700',
  failed: 'bg-red-900/40 text-red-300 border-red-700',
};

const STATUS_LABELS: Record<DocumentStatus, string> = {
  queued: 'Queued',
  processing: 'Processing…',
  ready: 'Ready',
  failed: 'Failed',
};

type SortKey = 'newest' | 'oldest';
type FilterStatus = 'all' | DocumentStatus;

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1_048_576) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1_048_576).toFixed(1)} MB`;
}

function StatusBadge({ status }: { status: DocumentStatus }) {
  return (
    <span
      className={`text-xs font-medium px-2 py-0.5 rounded border ${STATUS_STYLES[status]}`}
      data-testid={`status-badge-${status}`}
    >
      {STATUS_LABELS[status]}
    </span>
  );
}

function DocumentRow({
  doc,
  onDeleteRequest,
}: {
  doc: DocumentResponse;
  onDeleteRequest: (id: string, title: string) => void;
}) {
  useQuery({
    queryKey: ['doc-status', doc.id],
    queryFn: () => documentsApi.getStatus(doc.id),
    refetchInterval: TERMINAL.includes(doc.status) ? false : 3000,
    enabled: !TERMINAL.includes(doc.status),
  });

  return (
    <div
      className="flex items-start justify-between gap-4 py-3 border-b border-gray-800 last:border-0"
      data-testid={`doc-row-${doc.id}`}
    >
      <div className="min-w-0 flex-1">
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
        <button
          onClick={() => onDeleteRequest(doc.id, doc.title)}
          className="text-gray-600 hover:text-red-400 transition-colors"
          aria-label={`Delete ${doc.title}`}
          data-testid={`delete-btn-${doc.id}`}
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.5}
              d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
            />
          </svg>
        </button>
      </div>
    </div>
  );
}

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
      aria-label="Upload document — click or drag and drop"
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
      data-testid="upload-zone"
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
        <span className="text-indigo-400">Click to upload</span> or drag &amp; drop
      </p>
      <p className="text-xs text-gray-600 mt-1">PDF, DOCX, TXT, MD, HTML — max 50 MB</p>
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPTED}
        className="hidden"
        onChange={handleChange}
        aria-label="File input"
      />
    </div>
  );
}

export function DocumentsPage() {
  const qc = useQueryClient();
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>('newest');
  const [filterStatus, setFilterStatus] = useState<FilterStatus>('all');
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; title: string } | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ['documents'],
    queryFn: () => documentsApi.list(1, 100),
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? [];
      return items.some((d) => !TERMINAL.includes(d.status)) ? 3000 : false;
    },
  });

  const uploadMutation = useMutation({
    mutationFn: (file: File) => documentsApi.upload(file, undefined, setUploadProgress),
    onSuccess: () => {
      setUploadProgress(null);
      qc.invalidateQueries({ queryKey: ['documents'] });
      toast.success('Document uploaded — processing started');
    },
    onError: (err: unknown) => {
      setUploadProgress(null);
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Upload failed.';
      toast.error(msg);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => documentsApi.delete(id),
    onSuccess: () => {
      setDeleteTarget(null);
      qc.invalidateQueries({ queryKey: ['documents'] });
      toast.success('Document deleted');
    },
    onError: () => {
      toast.error('Delete failed — please try again');
    },
  });

  const filtered = (data?.items ?? [])
    .filter((d) => filterStatus === 'all' || d.status === filterStatus)
    .sort((a, b) => {
      const ta = new Date(a.created_at).getTime();
      const tb = new Date(b.created_at).getTime();
      return sortKey === 'newest' ? tb - ta : ta - tb;
    });

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="max-w-2xl mx-auto">
        <div className="mb-6">
          <h1 className="font-semibold text-xl text-gray-100">Documents</h1>
          <p className="text-sm text-gray-500 mt-1">Upload and manage your knowledge base files</p>
        </div>

        <div className="mb-4">
          <UploadZone onFile={(f) => uploadMutation.mutate(f)} />
          {uploadProgress !== null && (
            <div className="mt-3" data-testid="upload-progress">
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
        </div>

        {/* Sort + filter controls */}
        <div className="flex items-center gap-3 mb-4">
          <select
            value={filterStatus}
            onChange={(e) => setFilterStatus(e.target.value as FilterStatus)}
            className="text-xs bg-gray-800 border border-gray-700 text-gray-300 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            aria-label="Filter by status"
          >
            <option value="all">All statuses</option>
            <option value="queued">Queued</option>
            <option value="processing">Processing</option>
            <option value="ready">Ready</option>
            <option value="failed">Failed</option>
          </select>

          <select
            value={sortKey}
            onChange={(e) => setSortKey(e.target.value as SortKey)}
            className="text-xs bg-gray-800 border border-gray-700 text-gray-300 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            aria-label="Sort order"
          >
            <option value="newest">Newest first</option>
            <option value="oldest">Oldest first</option>
          </select>
        </div>

        <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6">
          <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest mb-4">
            Your documents
            {data && (
              <span className="ml-2 text-gray-600 normal-case font-normal">
                ({filtered.length} of {data.total})
              </span>
            )}
          </h2>

          {isLoading && <p className="text-sm text-gray-400 py-4 text-center">Loading…</p>}

          {!isLoading && filtered.length === 0 && (
            <div className="flex flex-col items-center py-10 text-center" data-testid="empty-state">
              <svg
                className="w-12 h-12 text-gray-700 mb-3"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1}
                  d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                />
              </svg>
              <p className="text-sm text-gray-600">
                {filterStatus === 'all'
                  ? 'No documents yet — upload your first file above.'
                  : `No documents with status "${filterStatus}".`}
              </p>
            </div>
          )}

          {filtered.map((doc) => (
            <DocumentRow
              key={doc.id}
              doc={doc}
              onDeleteRequest={(id, title) => setDeleteTarget({ id, title })}
            />
          ))}
        </div>
      </div>

      <Modal open={!!deleteTarget} onClose={() => setDeleteTarget(null)} title="Delete document?">
        <p className="text-sm text-gray-400 mb-1">
          Are you sure you want to delete{' '}
          <span className="font-medium text-gray-200">{deleteTarget?.title}</span>?
        </p>
        <p className="text-xs text-gray-600 mb-5">
          All chunks and embeddings will be permanently removed.
        </p>
        <div className="flex gap-3">
          <button
            onClick={() => deleteTarget && deleteMutation.mutate(deleteTarget.id)}
            disabled={deleteMutation.isPending}
            className="flex-1 py-2 text-sm font-medium text-white bg-red-600 hover:bg-red-500 disabled:opacity-50 rounded-lg transition-colors"
            data-testid="confirm-delete-btn"
          >
            {deleteMutation.isPending ? 'Deleting…' : 'Delete'}
          </button>
          <button
            onClick={() => setDeleteTarget(null)}
            className="flex-1 py-2 text-sm font-medium text-gray-300 bg-gray-700 hover:bg-gray-600 rounded-lg transition-colors"
          >
            Cancel
          </button>
        </div>
      </Modal>
    </div>
  );
}
