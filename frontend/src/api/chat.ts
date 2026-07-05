/**
 * chat.ts — Typed API client for the Veridian Chat API (Part 7).
 *
 * Covers:
 *  - streamQuery()        — POST /chat/query → SSE stream consumer
 *  - listSessions()       — GET  /chat/sessions
 *  - getSessionHistory()  — GET  /chat/sessions/{id}/history
 *  - deleteSession()      — DELETE /chat/sessions/{id}
 *
 * SSE event union (ChatEvent)
 * ---------------------------
 * | type    | fields                                                     |
 * |---------|------------------------------------------------------------|
 * | "token" | content: string                                            |
 * | "done"  | session_id, message_id, citations, model, token counts     |
 * | "error" | message: string                                            |
 */

import { apiClient } from './client';
import { useAuthStore } from '../store/authStore';

// ── Domain types ──────────────────────────────────────────────────────────────

export interface Citation {
  chunk_id: string;
  document_id: string;
  chunk_index: number;
  page_number: number | null;
  snippet: string;
  source_filename: string;
  score: number;
}

export interface ChatMessage {
  id: string;
  session_id: string;
  user_id: string;
  role: 'user' | 'assistant';
  content: string;
  sources: Citation[] | null;
  token_count: number | null;
  created_at: string;
}

export interface ChatSession {
  id: string;
  user_id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
  messages: ChatMessage[];
}

export interface ChatSessionList {
  items: ChatSession[];
  total: number;
  page: number;
  size: number;
  pages: number;
}

// ── SSE event union ───────────────────────────────────────────────────────────

export interface ChatTokenEvent {
  type: 'token';
  content: string;
}

export interface ChatDoneEvent {
  type: 'done';
  session_id: string;
  message_id: string;
  citations: Citation[];
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
}

export interface ChatErrorEvent {
  type: 'error';
  message: string;
}

export type ChatEvent = ChatTokenEvent | ChatDoneEvent | ChatErrorEvent;

// ── Request type ──────────────────────────────────────────────────────────────

export interface ChatQueryRequest {
  message: string;
  session_id?: string;
}

// ── SSE streaming consumer ────────────────────────────────────────────────────

export interface StreamQueryCallbacks {
  /** Called for each incremental token from the LLM. */
  onToken: (token: string) => void;
  /** Called once when the stream completes successfully. */
  onDone: (event: ChatDoneEvent) => void;
  /** Called if the stream encounters a terminal error. */
  onError: (event: ChatErrorEvent) => void;
}

/**
 * POST /chat/query — open an SSE stream and dispatch events to callbacks.
 *
 * Returns an AbortController so the caller can cancel the stream.
 *
 * @example
 * const abort = streamQuery(
 *   { message: "What are mitochondria?" },
 *   token => setPartialResponse(r => r + token),
 *   done  => setSources(done.citations),
 *   err   => setError(err.message),
 * );
 * // to cancel: abort.abort();
 */
export function streamQuery(
  request: ChatQueryRequest,
  callbacks: StreamQueryCallbacks,
): AbortController {
  const controller = new AbortController();

  const token = useAuthStore.getState().accessToken ?? '';

  const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

  fetch(`${BASE_URL}/chat/query`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(request),
    signal: controller.signal,
  })
    .then(async (response) => {
      if (!response.ok || !response.body) {
        callbacks.onError({
          type: 'error',
          message: `HTTP ${response.status}: ${response.statusText}`,
        });
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        // Keep the last (potentially incomplete) line in the buffer
        buffer = lines.pop() ?? '';

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed.startsWith('data: ')) continue;
          const payload = trimmed.slice(6).trim();
          if (!payload) continue;

          let event: ChatEvent;
          try {
            event = JSON.parse(payload) as ChatEvent;
          } catch {
            continue; // skip malformed lines
          }

          switch (event.type) {
            case 'token':
              callbacks.onToken(event.content);
              break;
            case 'done':
              callbacks.onDone(event);
              break;
            case 'error':
              callbacks.onError(event);
              break;
          }
        }
      }
    })
    .catch((err: unknown) => {
      if (err instanceof Error && err.name === 'AbortError') return; // cancelled by caller
      callbacks.onError({
        type: 'error',
        message: err instanceof Error ? err.message : String(err),
      });
    });

  return controller;
}

// ── REST helpers ──────────────────────────────────────────────────────────────

/**
 * GET /chat/sessions — paginated list of the current user's sessions.
 */
export async function listSessions(
  page = 1,
  size = 20,
): Promise<ChatSessionList> {
  const { data } = await apiClient.get<ChatSessionList>('/chat/sessions', {
    params: { page, size },
  });
  return data;
}

/**
 * GET /chat/sessions/{sessionId}/history — full message history.
 */
export async function getSessionHistory(sessionId: string): Promise<ChatSession> {
  const { data } = await apiClient.get<ChatSession>(
    `/chat/sessions/${sessionId}/history`,
  );
  return data;
}

/**
 * DELETE /chat/sessions/{sessionId} — remove a session and its messages.
 */
export async function deleteSession(sessionId: string): Promise<void> {
  await apiClient.delete(`/chat/sessions/${sessionId}`);
}
