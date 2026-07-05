import { useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { authApi, type UserResponse } from '../api/auth';
import { useAuthStore } from '../store/authStore';

export function DashboardPage() {
  const navigate = useNavigate();
  const { logout, setUser, refreshToken } = useAuthStore();

  const { data: user, isLoading } = useQuery<UserResponse>({
    queryKey: ['me'],
    queryFn: authApi.me,
    retry: false,
  });

  useEffect(() => {
    if (user) setUser(user);
  }, [user, setUser]);

  async function handleLogout() {
    if (refreshToken) {
      try {
        await authApi.logout(refreshToken);
      } catch {
        // best-effort
      }
    }
    logout();
    navigate('/login');
  }

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
              <h1 className="font-semibold text-lg leading-none">Veridian</h1>
              <p className="text-xs text-gray-500 mt-0.5">Dashboard</p>
            </div>
          </div>
          <button
            onClick={handleLogout}
            className="text-xs text-gray-400 hover:text-gray-200 border border-gray-700 hover:border-gray-500 px-3 py-1.5 rounded-lg transition-colors"
          >
            Sign out
          </button>
        </div>

        {/* Profile card */}
        <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6 mb-6">
          <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest mb-4">
            Your profile
          </h2>
          {isLoading ? (
            <p className="text-sm text-gray-400">Loading…</p>
          ) : user ? (
            <dl className="space-y-3">
              <div className="flex justify-between text-sm">
                <dt className="text-gray-400">Name</dt>
                <dd className="text-gray-200 font-medium">
                  {user.full_name ?? <span className="text-gray-600 italic">not set</span>}
                </dd>
              </div>
              <div className="flex justify-between text-sm border-t border-gray-800 pt-3">
                <dt className="text-gray-400">Email</dt>
                <dd className="text-gray-200 font-mono text-xs">{user.email}</dd>
              </div>
              <div className="flex justify-between text-sm border-t border-gray-800 pt-3">
                <dt className="text-gray-400">Member since</dt>
                <dd className="text-gray-200 text-xs">
                  {new Date(user.created_at).toLocaleDateString()}
                </dd>
              </div>
            </dl>
          ) : (
            <p className="text-sm text-red-400">Failed to load profile.</p>
          )}
        </div>

        {/* Quick links */}
        <div className="flex gap-4 justify-center text-xs text-gray-600">
          <Link to="/documents" className="text-indigo-400 hover:text-indigo-300">
            Documents →
          </Link>
          <Link to="/" className="text-indigo-400 hover:text-indigo-300">
            System health →
          </Link>
        </div>
      </div>
    </div>
  );
}
