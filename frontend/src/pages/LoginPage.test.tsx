import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { LoginPage } from './LoginPage';
import * as authApiModule from '../api/auth';

// ── helpers ───────────────────────────────────────────────────────────────────

function renderLogin() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter initialEntries={['/login']}>
      <QueryClientProvider client={qc}>
        <LoginPage />
      </QueryClientProvider>
    </MemoryRouter>
  );
}

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async (importActual) => {
  const actual = await importActual<typeof import('react-router-dom')>();
  return { ...actual, useNavigate: () => mockNavigate };
});

vi.mock('../api/auth');

// ── tests ─────────────────────────────────────────────────────────────────────

describe('LoginPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders email and password fields', () => {
    renderLogin();
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
  });

  it('renders submit button', () => {
    renderLogin();
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
  });

  it('shows error when submitted with empty fields (HTML5 validation)', async () => {
    renderLogin();
    const emailInput = screen.getByLabelText(/email/i);
    // HTML required attribute prevents submission — input is invalid
    expect(emailInput).toBeRequired();
    expect(screen.getByLabelText(/password/i)).toBeRequired();
  });

  it('calls authApi.login with entered credentials on submit', async () => {
    vi.mocked(authApiModule.authApi.login).mockResolvedValue({
      access_token: 'acc',
      refresh_token: 'ref',
      token_type: 'bearer',
      expires_in: 900,
    });

    renderLogin();
    await userEvent.type(screen.getByLabelText(/email/i), 'user@example.com');
    await userEvent.type(screen.getByLabelText(/password/i), 'mypassword');
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => {
      expect(authApiModule.authApi.login).toHaveBeenCalledWith('user@example.com', 'mypassword');
    });
  });

  it('navigates to /dashboard on successful login', async () => {
    vi.mocked(authApiModule.authApi.login).mockResolvedValue({
      access_token: 'acc',
      refresh_token: 'ref',
      token_type: 'bearer',
      expires_in: 900,
    });

    renderLogin();
    await userEvent.type(screen.getByLabelText(/email/i), 'user@example.com');
    await userEvent.type(screen.getByLabelText(/password/i), 'mypassword');
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/dashboard'));
  });

  it('shows API error message on failed login', async () => {
    vi.mocked(authApiModule.authApi.login).mockRejectedValue({
      response: { data: { detail: 'Invalid email or password.' } },
    });

    renderLogin();
    await userEvent.type(screen.getByLabelText(/email/i), 'bad@example.com');
    await userEvent.type(screen.getByLabelText(/password/i), 'wrongpassword');
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByText(/invalid email or password/i)).toBeInTheDocument();
    });
  });

  it('disables submit button while loading', async () => {
    // Never resolves so the button stays disabled
    vi.mocked(authApiModule.authApi.login).mockReturnValue(new Promise(() => {}));

    renderLogin();
    await userEvent.type(screen.getByLabelText(/email/i), 'user@example.com');
    await userEvent.type(screen.getByLabelText(/password/i), 'mypassword');
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }));

    expect(screen.getByRole('button', { name: /signing in/i })).toBeDisabled();
  });
});
