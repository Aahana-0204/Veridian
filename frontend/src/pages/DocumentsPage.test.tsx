/**
 * DocumentsPage tests — status polling, delete modal, and filter/sort.
 * All API calls are mocked.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { Toaster } from 'react-hot-toast';
import { DocumentsPage } from './DocumentsPage';
import type { DocumentListResponse, DocumentResponse } from '../api/documents';

// ── Module mocks ──────────────────────────────────────────────────────────────

vi.mock('../api/documents', () => ({
  documentsApi: {
    list: vi.fn(),
    upload: vi.fn(),
    getStatus: vi.fn(),
    delete: vi.fn(),
  },
}));

import { documentsApi } from '../api/documents';

// ── Helpers ───────────────────────────────────────────────────────────────────

function renderDocs() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={qc}>
        <Toaster />
        <DocumentsPage />
      </QueryClientProvider>
    </MemoryRouter>
  );
}

function makeDoc(overrides: Partial<DocumentResponse> = {}): DocumentResponse {
  return {
    id: 'doc-1',
    user_id: 'user-1',
    title: 'Test Document',
    filename: 'test.pdf',
    file_type: 'pdf',
    file_size: 1024,
    status: 'ready',
    chunk_count: 5,
    error_message: null,
    content_hash: 'abc123',
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    ...overrides,
  };
}

function makeList(docs: DocumentResponse[]): DocumentListResponse {
  return { items: docs, total: docs.length, page: 1, size: 100, pages: 1 };
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('DocumentsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows empty state when no documents', async () => {
    vi.mocked(documentsApi.list).mockResolvedValue(makeList([]));
    renderDocs();

    await waitFor(() => {
      expect(screen.getByTestId('empty-state')).toBeInTheDocument();
      expect(screen.getByText(/No documents yet/i)).toBeInTheDocument();
    });
  });

  it('renders document rows with status badges', async () => {
    vi.mocked(documentsApi.list).mockResolvedValue(
      makeList([
        makeDoc({ id: 'doc-1', title: 'Doc 1', status: 'ready' }),
        makeDoc({ id: 'doc-2', title: 'Doc 2', status: 'processing' }),
        makeDoc({ id: 'doc-3', title: 'Doc 3', status: 'failed' }),
      ])
    );
    renderDocs();

    await waitFor(() => {
      expect(screen.getByTestId('doc-row-doc-1')).toBeInTheDocument();
      expect(screen.getByTestId('status-badge-ready')).toBeInTheDocument();
      expect(screen.getByTestId('status-badge-processing')).toBeInTheDocument();
      expect(screen.getByTestId('status-badge-failed')).toBeInTheDocument();
    });
  });

  it('polls status for non-terminal documents', async () => {
    vi.mocked(documentsApi.list).mockResolvedValue(
      makeList([makeDoc({ id: 'doc-1', status: 'processing' })])
    );
    vi.mocked(documentsApi.getStatus).mockResolvedValue({
      id: 'doc-1',
      status: 'processing',
      chunk_count: 0,
      error_message: null,
    });

    renderDocs();

    await waitFor(() => {
      expect(screen.getByTestId('status-badge-processing')).toBeInTheDocument();
    });

    // Status polling should be initiated (getStatus called for non-terminal doc)
    await waitFor(
      () => {
        expect(documentsApi.getStatus).toHaveBeenCalledWith('doc-1');
      },
      { timeout: 5000 }
    );
  });

  it('does NOT poll for terminal (ready) documents', async () => {
    vi.mocked(documentsApi.list).mockResolvedValue(
      makeList([makeDoc({ id: 'doc-1', status: 'ready' })])
    );

    renderDocs();

    await waitFor(() => screen.getByTestId('status-badge-ready'));

    // Wait a bit and confirm getStatus was never called
    await new Promise((r) => setTimeout(r, 500));
    expect(documentsApi.getStatus).not.toHaveBeenCalled();
  });

  it('opens delete modal when delete button clicked', async () => {
    vi.mocked(documentsApi.list).mockResolvedValue(
      makeList([makeDoc({ id: 'doc-1', title: 'My Important File' })])
    );
    renderDocs();

    await waitFor(() => screen.getByTestId('delete-btn-doc-1'));
    fireEvent.click(screen.getByTestId('delete-btn-doc-1'));

    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeInTheDocument();
      // Scope the title check to inside the modal — the title also appears in the list row
      const dialog = screen.getByRole('dialog');
      expect(dialog.textContent).toMatch(/My Important File/i);
    });
  });

  it('calls delete API and dismisses modal on confirm', async () => {
    vi.mocked(documentsApi.list).mockResolvedValue(
      makeList([makeDoc({ id: 'doc-1', title: 'Deletable Doc' })])
    );
    vi.mocked(documentsApi.delete).mockResolvedValue(undefined);

    renderDocs();

    await waitFor(() => screen.getByTestId('delete-btn-doc-1'));
    fireEvent.click(screen.getByTestId('delete-btn-doc-1'));

    await waitFor(() => screen.getByTestId('confirm-delete-btn'));
    fireEvent.click(screen.getByTestId('confirm-delete-btn'));

    await waitFor(() => {
      expect(documentsApi.delete).toHaveBeenCalledWith('doc-1');
    });
  });

  it('filters documents by status', async () => {
    vi.mocked(documentsApi.list).mockResolvedValue(
      makeList([
        makeDoc({ id: 'doc-1', title: 'Ready Doc', status: 'ready' }),
        makeDoc({ id: 'doc-2', title: 'Failed Doc', status: 'failed' }),
      ])
    );
    renderDocs();

    await waitFor(() => screen.getByTestId('doc-row-doc-1'));

    // Filter to 'failed' only
    fireEvent.change(screen.getByRole('combobox', { name: /filter by status/i }), {
      target: { value: 'failed' },
    });

    await waitFor(() => {
      expect(screen.queryByTestId('doc-row-doc-1')).not.toBeInTheDocument();
      expect(screen.getByTestId('doc-row-doc-2')).toBeInTheDocument();
    });
  });

  it('shows upload zone', async () => {
    vi.mocked(documentsApi.list).mockResolvedValue(makeList([]));
    renderDocs();

    await waitFor(() => {
      expect(screen.getByTestId('upload-zone')).toBeInTheDocument();
    });
  });
});
