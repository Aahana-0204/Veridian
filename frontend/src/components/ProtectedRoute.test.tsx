import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, it, expect, afterEach } from 'vitest';
import { ProtectedRoute } from './ProtectedRoute';
import { useAuthStore } from '../store/authStore';

// ── helpers ───────────────────────────────────────────────────────────────────

function DummyDashboard() {
  return <div>Dashboard content</div>;
}

function DummyLogin() {
  return <div>Login page</div>;
}

function renderWithAuth(isAuthenticated: boolean) {
  useAuthStore.setState({
    isAuthenticated,
    accessToken: isAuthenticated ? 'fake-token' : null,
    refreshToken: isAuthenticated ? 'fake-refresh' : null,
    user: null,
  });

  return render(
    <MemoryRouter initialEntries={['/dashboard']}>
      <Routes>
        <Route path="/login" element={<DummyLogin />} />
        <Route element={<ProtectedRoute />}>
          <Route path="/dashboard" element={<DummyDashboard />} />
        </Route>
      </Routes>
    </MemoryRouter>
  );
}

// ── tests ─────────────────────────────────────────────────────────────────────

describe('ProtectedRoute', () => {
  afterEach(() => {
    useAuthStore.setState({
      isAuthenticated: false,
      accessToken: null,
      refreshToken: null,
      user: null,
    });
  });

  it('renders the protected child route when authenticated', () => {
    renderWithAuth(true);
    expect(screen.getByText('Dashboard content')).toBeInTheDocument();
    expect(screen.queryByText('Login page')).not.toBeInTheDocument();
  });

  it('redirects to /login when NOT authenticated', () => {
    renderWithAuth(false);
    expect(screen.getByText('Login page')).toBeInTheDocument();
    expect(screen.queryByText('Dashboard content')).not.toBeInTheDocument();
  });
});
