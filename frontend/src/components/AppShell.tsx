/**
 * AppShell — global layout with sidebar navigation.
 *
 * Desktop: fixed left sidebar (240 px) + scrollable main content.
 * Mobile  : top bar + collapsible sidebar overlay.
 *
 * Navigation items: Documents, Chat.
 * Footer: current user email + logout button.
 */
import { useEffect, useState } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useAuthStore } from '../store/authStore';
import { authApi } from '../api/auth';
import toast from 'react-hot-toast';

const NAV_ITEMS = [
  {
    to: '/documents',
    label: 'Documents',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={1.5}
          d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
        />
      </svg>
    ),
  },
  {
    to: '/chat',
    label: 'Chat',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={1.5}
          d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
        />
      </svg>
    ),
  },
];

export function AppShell() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const { user, refreshToken, logout, setUser } = useAuthStore();
  const navigate = useNavigate();

  // Fetch current user on mount if not already loaded
  const { data: fetchedUser } = useQuery({
    queryKey: ['me'],
    queryFn: authApi.me,
    enabled: !user,
    retry: false,
  });
  useEffect(() => {
    if (fetchedUser && !user) setUser(fetchedUser);
  }, [fetchedUser, user, setUser]);

  const handleLogout = async () => {
    try {
      if (refreshToken) await authApi.logout(refreshToken);
    } catch {
      // Ignore logout API errors — clear state anyway
    }
    logout();
    toast.success('Logged out');
    navigate('/login');
  };

  const sidebar = (
    <nav className="flex flex-col h-full bg-gray-950 border-r border-gray-800">
      {/* Logo */}
      <div className="flex items-center gap-3 px-5 py-5">
        <div className="w-8 h-8 rounded-lg bg-indigo-600 flex items-center justify-center shrink-0">
          <span className="text-white font-bold text-sm">V</span>
        </div>
        <span className="font-semibold text-gray-100 text-base tracking-tight">Veridian</span>
      </div>

      {/* Nav links */}
      <div className="flex-1 px-3 py-2 space-y-1">
        {NAV_ITEMS.map(({ to, label, icon }) => (
          <NavLink
            key={to}
            to={to}
            onClick={() => setSidebarOpen(false)}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                isActive
                  ? 'bg-indigo-600/20 text-indigo-300'
                  : 'text-gray-400 hover:text-gray-100 hover:bg-gray-800'
              }`
            }
          >
            {icon}
            {label}
          </NavLink>
        ))}
      </div>

      {/* User info + logout */}
      <div className="px-4 py-4 border-t border-gray-800">
        {user && (
          <p className="text-xs text-gray-500 truncate mb-2" title={user.email}>
            {user.full_name ?? user.email}
          </p>
        )}
        <button
          onClick={handleLogout}
          className="w-full text-left text-xs text-gray-500 hover:text-red-400 transition-colors"
        >
          Sign out
        </button>
      </div>
    </nav>
  );

  return (
    <div className="flex h-screen bg-gray-950 overflow-hidden">
      {/* Desktop sidebar */}
      <div className="hidden md:flex w-60 shrink-0 flex-col">{sidebar}</div>

      {/* Mobile sidebar overlay */}
      {sidebarOpen && (
        <div className="md:hidden fixed inset-0 z-40 flex">
          <div
            className="absolute inset-0 bg-black/60"
            onClick={() => setSidebarOpen(false)}
            aria-hidden="true"
          />
          <div className="relative z-50 w-60 shrink-0 flex flex-col">{sidebar}</div>
        </div>
      )}

      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Mobile top bar */}
        <div className="md:hidden flex items-center gap-3 px-4 py-3 border-b border-gray-800 bg-gray-950">
          <button
            onClick={() => setSidebarOpen(true)}
            className="p-1 text-gray-400 hover:text-gray-100"
            aria-label="Open navigation"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M4 6h16M4 12h16M4 18h16"
              />
            </svg>
          </button>
          <span className="font-semibold text-gray-100 text-sm">Veridian</span>
        </div>

        {/* Page content */}
        <div className="flex-1 overflow-auto">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
