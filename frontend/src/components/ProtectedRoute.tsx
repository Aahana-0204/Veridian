import { Navigate, Outlet } from 'react-router-dom';
import { useAuthStore } from '../store/authStore';

/**
 * Wraps protected routes. Redirects to /login when not authenticated.
 * Usage: <Route element={<ProtectedRoute />}><Route path="/dashboard" ... /></Route>
 */
export function ProtectedRoute() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  return isAuthenticated ? <Outlet /> : <Navigate to="/login" replace />;
}
