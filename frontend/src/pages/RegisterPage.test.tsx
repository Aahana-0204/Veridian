import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { RegisterPage } from './RegisterPage';
import * as authApiModule from '../api/auth';

// ── helpers ───────────────────────────────────────────────────────────────────

function renderRegister() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter initialEntries={['/register']}>
      <QueryClientProvider client={qc}>
        <RegisterPage />
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

describe('RegisterPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders email, password, and full-name fields', () => {
    renderRegister();
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/full name/i)).toBeInTheDocument();
  });

  it('email and password fields are required', () => {
    renderRegister();
    expect(screen.getByLabelText(/email/i)).toBeRequired();
    expect(screen.getByLabelText(/password/i)).toBeRequired();
  });

  it('password field enforces minimum length of 8 via HTML5', () => {
    renderRegister();
    const pw = screen.getByLabelText(/password/i);
    expect(pw).toHaveAttribute('minLength', '8');
  });

  it('calls authApi.register with entered values on submit', async () => {
    vi.mocked(authApiModule.authApi.register).mockResolvedValue({
      access_token: 'acc',
      refresh_token: 'ref',
      token_type: 'bearer',
      expires_in: 900,
    });

    renderRegister();
    await userEvent.type(screen.getByLabelText(/full name/i), 'Alice Smith');
    await userEvent.type(screen.getByLabelText(/email/i), 'alice@example.com');
    await userEvent.type(screen.getByLabelText(/password/i), 'strongpass');
    await userEvent.click(screen.getByRole('button', { name: /create account/i }));

    await waitFor(() => {
      expect(authApiModule.authApi.register).toHaveBeenCalledWith(
        'alice@example.com',
        'strongpass',
        'Alice Smith'
      );
    });
  });

  it('navigates to /dashboard on successful registration', async () => {
    vi.mocked(authApiModule.authApi.register).mockResolvedValue({
      access_token: 'acc',
      refresh_token: 'ref',
      token_type: 'bearer',
      expires_in: 900,
    });

    renderRegister();
    await userEvent.type(screen.getByLabelText(/email/i), 'alice@example.com');
    await userEvent.type(screen.getByLabelText(/password/i), 'strongpass');
    await userEvent.click(screen.getByRole('button', { name: /create account/i }));

    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/dashboard'));
  });

  it('shows API error on conflict (duplicate email)', async () => {
    vi.mocked(authApiModule.authApi.register).mockRejectedValue({
      response: { data: { detail: 'An account with this email already exists.' } },
    });

    renderRegister();
    await userEvent.type(screen.getByLabelText(/email/i), 'dup@example.com');
    await userEvent.type(screen.getByLabelText(/password/i), 'strongpass');
    await userEvent.click(screen.getByRole('button', { name: /create account/i }));

    await waitFor(() => {
      expect(screen.getByText(/an account with this email already exists/i)).toBeInTheDocument();
    });
  });

  it('omits full_name when left blank', async () => {
    vi.mocked(authApiModule.authApi.register).mockResolvedValue({
      access_token: 'acc',
      refresh_token: 'ref',
      token_type: 'bearer',
      expires_in: 900,
    });

    renderRegister();
    await userEvent.type(screen.getByLabelText(/email/i), 'noname@example.com');
    await userEvent.type(screen.getByLabelText(/password/i), 'strongpass');
    await userEvent.click(screen.getByRole('button', { name: /create account/i }));

    await waitFor(() => {
      expect(authApiModule.authApi.register).toHaveBeenCalledWith(
        'noname@example.com',
        'strongpass',
        undefined // blank full_name → undefined
      );
    });
  });
});
