/**
 * ChatPage tests — citation expansion and session sidebar interactions.
 * All API calls are mocked.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { Toaster } from 'react-hot-toast';

// ── Module mocks ──────────────────────────────────────────────────────────────

vi.mock('../api/chat', () => ({
  streamQuery: vi.fn(),
  listSessions: vi.fn(),
  getSessionHistory: vi.fn(),
  deleteSession: vi.fn(),
}));

import * as chatApi from '../api/chat';
import { ChatPage } from './ChatPage';

// ── Helpers ───────────────────────────────────────────────────────────────────

function renderChat() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={qc}>
        <Toaster />
        <ChatPage />
      </QueryClientProvider>
    </MemoryRouter>
  );
}

const MOCK_CITATION = {
  chunk_id: 'chunk-1',
  document_id: 'doc-1',
  chunk_index: 0,
  page_number: 2,
  snippet: 'The mitochondria is the powerhouse of the cell.',
  source_filename: 'biology.pdf',
  score: 0.95,
};

const MOCK_SESSIONS = {
  items: [
    {
      id: 'session-1',
      title: 'Cell biology questions',
      user_id: 'user-1',
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-01T00:00:00Z',
      messages: [],
    },
    {
      id: 'session-2',
      title: 'Chemistry notes',
      user_id: 'user-1',
      created_at: '2024-01-02T00:00:00Z',
      updated_at: '2024-01-02T00:00:00Z',
      messages: [],
    },
  ],
  total: 2,
  page: 1,
  size: 50,
  pages: 1,
};

// ── Citation tests ─────────────────────────────────────────────────────────────

describe('CitationList', () => {
  beforeEach(() => {
    vi.mocked(chatApi.listSessions).mockResolvedValue(MOCK_SESSIONS);
    vi.mocked(chatApi.streamQuery).mockImplementation((_req, callbacks) => {
      // Emit a token, then a done event with one citation
      setTimeout(() => {
        callbacks.onToken('The mitochondria ');
        callbacks.onToken('is the powerhouse.');
        callbacks.onDone({
          type: 'done',
          session_id: 'session-new',
          message_id: 'msg-asst-1',
          citations: [MOCK_CITATION],
          model: 'fake',
          prompt_tokens: 10,
          completion_tokens: 8,
        });
      }, 0);
      return new AbortController();
    });
  });

  it('shows citation list after message completes', async () => {
    renderChat();
    const user = userEvent.setup();

    const input = screen.getByRole('textbox', { name: /chat message/i });
    await user.type(input, 'What are mitochondria?');
    await user.keyboard('{Enter}');

    // Wait for citation list to appear
    await waitFor(
      () => {
        expect(screen.getByTestId('citation-list')).toBeInTheDocument();
      },
      { timeout: 3000 }
    );

    expect(screen.getByText(/biology\.pdf/i)).toBeInTheDocument();
  });

  it('expands citation on click to show snippet', async () => {
    renderChat();
    const user = userEvent.setup();

    const input = screen.getByRole('textbox', { name: /chat message/i });
    await user.type(input, 'Tell me about cells');
    await user.keyboard('{Enter}');

    // Wait for done
    await waitFor(
      () => expect(screen.getByTestId('citation-list')).toBeInTheDocument(),
      { timeout: 3000 }
    );

    // Citation is collapsed — snippet not visible
    expect(screen.queryByTestId('citation-snippet-0')).not.toBeInTheDocument();

    // Click toggle
    fireEvent.click(screen.getByTestId('citation-toggle-0'));

    // Snippet now visible
    await waitFor(() => {
      expect(screen.getByTestId('citation-snippet-0')).toBeInTheDocument();
      expect(
        screen.getByText(/The mitochondria is the powerhouse of the cell\./i)
      ).toBeInTheDocument();
    });
  });

  it('collapses citation on second click', async () => {
    renderChat();
    const user = userEvent.setup();

    const input = screen.getByRole('textbox', { name: /chat message/i });
    await user.type(input, 'Biology question');
    await user.keyboard('{Enter}');

    await waitFor(
      () => expect(screen.getByTestId('citation-list')).toBeInTheDocument(),
      { timeout: 3000 }
    );

    const toggle = screen.getByTestId('citation-toggle-0');
    fireEvent.click(toggle); // expand
    await waitFor(() =>
      expect(screen.getByTestId('citation-snippet-0')).toBeInTheDocument()
    );

    fireEvent.click(toggle); // collapse
    await waitFor(() =>
      expect(screen.queryByTestId('citation-snippet-0')).not.toBeInTheDocument()
    );
  });
});

// ── Session sidebar tests ──────────────────────────────────────────────────────

describe('SessionSidebar', () => {
  beforeEach(() => {
    vi.mocked(chatApi.listSessions).mockResolvedValue(MOCK_SESSIONS);
    vi.mocked(chatApi.streamQuery).mockReturnValue(new AbortController());
    vi.mocked(chatApi.getSessionHistory).mockResolvedValue({
      id: 'session-1',
      title: 'Cell biology questions',
      user_id: 'user-1',
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-01T00:00:00Z',
      messages: [
        {
          id: 'msg-1',
          session_id: 'session-1',
          user_id: 'user-1',
          role: 'user' as const,
          content: 'What is a cell?',
          sources: null,
          token_count: null,
          created_at: '2024-01-01T00:01:00Z',
        },
      ],
    });
  });

  it('renders session list', async () => {
    renderChat();

    await waitFor(() => {
      expect(screen.getByTestId('session-sidebar')).toBeInTheDocument();
      expect(screen.getByText('Cell biology questions')).toBeInTheDocument();
      expect(screen.getByText('Chemistry notes')).toBeInTheDocument();
    });
  });

  it('loads session history when clicking a session', async () => {
    renderChat();

    await waitFor(() =>
      expect(screen.getByTestId('session-btn-session-1')).toBeInTheDocument()
    );

    fireEvent.click(screen.getByTestId('session-btn-session-1'));

    await waitFor(() => {
      expect(chatApi.getSessionHistory).toHaveBeenCalledWith('session-1');
      expect(screen.getByText('What is a cell?')).toBeInTheDocument();
    });
  });

  it('shows delete modal and calls deleteSession on confirm', async () => {
    vi.mocked(chatApi.deleteSession).mockResolvedValue(undefined);
    renderChat();

    await waitFor(() =>
      expect(screen.getByTestId('session-delete-session-1')).toBeInTheDocument()
    );

    fireEvent.click(screen.getByTestId('session-delete-session-1'));

    // Modal appears
    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeInTheDocument();
      expect(screen.getByText(/Delete chat session\?/i)).toBeInTheDocument();
    });

    // Confirm deletion
    fireEvent.click(screen.getByText('Delete'));

    await waitFor(() => {
      expect(chatApi.deleteSession).toHaveBeenCalledWith('session-1');
    });
  });

  it('clicking New Chat clears the message list', async () => {
    renderChat();

    await waitFor(() => expect(screen.getByTestId('new-chat-btn')).toBeInTheDocument());

    // First load a session — wait for sidebar to finish loading before clicking
    await waitFor(() => expect(screen.getByTestId('session-btn-session-1')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('session-btn-session-1'));
    await waitFor(() => expect(screen.getByText('What is a cell?')).toBeInTheDocument());

    // Click New Chat
    fireEvent.click(screen.getByTestId('new-chat-btn'));

    // Message list cleared → back to empty state
    await waitFor(() => {
      expect(screen.queryByText('What is a cell?')).not.toBeInTheDocument();
      expect(screen.getByText(/Ask Veridian/i)).toBeInTheDocument();
    });
  });
});
